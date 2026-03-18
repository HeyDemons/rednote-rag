"""
Authentication endpoints for rednote-rag.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_context
from app.error_handling import raise_api_error
from app.models import (
    AuthSessionResponse,
    BrowserLoginRequest,
    LogoutRequest,
    QrLoginStartResponse,
    QrLoginStatusResponse,
    SessionUserInfo,
    UserSession,
)
from app.services.xhs_cli_service import XhsCliService
from app.time_utils import utc_now


router = APIRouter(prefix="/auth", tags=["auth"])
login_sessions: dict[str, dict] = {}
pending_qr_logins: dict[str, dict] = {}


def _to_user_info(payload: dict) -> SessionUserInfo:
    return SessionUserInfo(
        user_id=str(payload.get("user_id", "")),
        username=str(payload.get("username", "")),
        nickname=str(payload.get("nickname", "Unknown")),
        avatar=str(payload.get("avatar", "")),
        ip_location=str(payload.get("ip_location", "")),
        desc=str(payload.get("desc", "")),
    )


async def _create_app_session(
    *,
    db: AsyncSession,
    service: XhsCliService,
    cookies: dict[str, str],
    user: dict,
    cookie_source: str,
) -> AuthSessionResponse:
    session_id = str(uuid.uuid4())
    cookie_json = XhsCliService.serialize_cookies(cookies)

    db_session = UserSession(
        session_id=session_id,
        xhs_user_id=user["user_id"],
        xhs_username=user["username"],
        xhs_nickname=user["nickname"],
        avatar=user["avatar"],
        cookie_json=cookie_json,
        is_valid=True,
        last_active_at=utc_now(),
    )
    db.add(db_session)
    await db.commit()

    login_sessions[session_id] = {
        "cookies": cookies,
        "user_info": user,
        "cookie_source": cookie_source,
    }

    return AuthSessionResponse(
        authenticated=True,
        session_id=session_id,
        user=_to_user_info(user),
        cookie_source=cookie_source,
    )


@router.post("/login/browser", response_model=AuthSessionResponse)
async def login_browser(
    request: BrowserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthSessionResponse:
    """Log in by extracting Xiaohongshu cookies from a local browser."""
    service = XhsCliService()
    try:
        result = service.login_with_browser_cookies(
            request.cookie_source,
            force_refresh=request.force_refresh,
        )
    except Exception as exc:
        logger.exception("浏览器登录失败 [{}]", request.cookie_source)
        raise_api_error(401, f"浏览器登录失败: {exc}", error_code="AUTH_BROWSER_LOGIN_FAILED")

    user = result["user"]
    if user["guest"] or not user["user_id"]:
        logger.warning("浏览器登录未完成验证 [{}]", request.cookie_source)
        raise_api_error(401, "Cookie 已获取，但当前会话未完成登录验证", error_code="AUTH_BROWSER_LOGIN_UNVERIFIED")

    return await _create_app_session(
        db=db,
        service=service,
        cookies=result["cookies"],
        user=user,
        cookie_source=result["cookie_source"],
    )


@router.post("/login/qrcode", response_model=QrLoginStartResponse)
async def login_qrcode() -> QrLoginStartResponse:
    """Start a QR-code login flow and return the QR URL for scanning."""
    service = XhsCliService()
    try:
        result = service.start_qrcode_login()
    except Exception as exc:
        logger.exception("二维码登录初始化失败")
        raise_api_error(500, f"二维码登录初始化失败: {exc}", error_code="QR_LOGIN_INIT_FAILED")

    login_id = str(uuid.uuid4())
    pending_qr_logins[login_id] = {
        "cookies": result["cookies"],
        "qr_id": result["qr_id"],
        "code": result["code"],
        "qr_url": result["qr_url"],
        "status": "waiting",
        "created_at": utc_now(),
        "session_id": None,
        "user": None,
    }
    return QrLoginStartResponse(login_id=login_id, qr_url=result["qr_url"])


@router.get("/login/qrcode/status/{login_id}", response_model=QrLoginStatusResponse)
async def login_qrcode_status(
    login_id: str,
    db: AsyncSession = Depends(get_db),
) -> QrLoginStatusResponse:
    """Poll QR-code login status and create an app session once confirmed."""
    state = pending_qr_logins.get(login_id)
    if not state:
        raise_api_error(404, "二维码登录任务不存在或已过期", error_code="QR_LOGIN_NOT_FOUND")

    age_seconds = int((utc_now() - state["created_at"]).total_seconds())
    expires_in_seconds = max(0, 240 - age_seconds)
    if expires_in_seconds <= 0 and not state.get("session_id"):
        state["status"] = "expired"
        return QrLoginStatusResponse(
            login_id=login_id,
            status="expired",
            expires_in_seconds=0,
            message="二维码已过期，请重新发起登录",
        )

    if state.get("session_id") and state.get("user"):
        return QrLoginStatusResponse(
            login_id=login_id,
            status="confirmed",
            authenticated=True,
            session_id=state["session_id"],
            user=_to_user_info(state["user"]),
            cookie_source="qrcode",
            expires_in_seconds=expires_in_seconds,
            message="登录成功",
        )

    service = XhsCliService()
    try:
        result = service.poll_qrcode_status(
            cookies=state["cookies"],
            qr_id=state["qr_id"],
            code=state["code"],
        )
    except Exception as exc:
        logger.exception("二维码登录状态查询失败 [{}]", login_id)
        raise_api_error(500, f"二维码登录状态查询失败: {exc}", error_code="QR_LOGIN_STATUS_FAILED")

    state["status"] = result["status"]
    if result["status"] != "confirmed":
        message = "等待扫码"
        if result["status"] == "scanned":
            message = "已扫码，等待确认"
        return QrLoginStatusResponse(
            login_id=login_id,
            status=result["status"],
            authenticated=False,
            expires_in_seconds=expires_in_seconds,
            message=message,
        )

    try:
        completed = service.complete_qrcode_login(
            cookies=state["cookies"],
            qr_id=state["qr_id"],
            code=state["code"],
            confirmed_user_id=result.get("confirmed_user_id", ""),
        )
    except Exception as exc:
        logger.exception("二维码登录完成失败 [{}]", login_id)
        raise_api_error(500, f"二维码登录完成失败: {exc}", error_code="QR_LOGIN_COMPLETE_FAILED")

    user = completed["user"]
    if user["guest"] or not user["user_id"]:
        logger.warning("二维码登录已确认但未完成验证 [{}]", login_id)
        raise_api_error(401, "二维码登录已确认，但当前会话未完成登录验证", error_code="QR_LOGIN_UNVERIFIED")

    session = await _create_app_session(
        db=db,
        service=service,
        cookies=completed["cookies"],
        user=user,
        cookie_source="qrcode",
    )
    state["session_id"] = session.session_id
    state["user"] = user
    state["status"] = "confirmed"

    return QrLoginStatusResponse(
        login_id=login_id,
        status="confirmed",
        authenticated=True,
        session_id=session.session_id,
        user=session.user,
        cookie_source="qrcode",
        expires_in_seconds=expires_in_seconds,
        message="登录成功",
    )


@router.get("/status", response_model=AuthSessionResponse)
async def auth_status(session_id: str | None = None) -> AuthSessionResponse:
    """Return either current saved-cookie status or a specific persisted session."""
    if session_id:
        session = await get_session(session_id)
        if not session:
            return AuthSessionResponse(authenticated=False)
        return AuthSessionResponse(
            authenticated=True,
            session_id=session_id,
            user=_to_user_info(session["user_info"]),
            cookie_source=session.get("cookie_source"),
        )

    service = XhsCliService()
    try:
        result = service.get_saved_login_status()
    except Exception as exc:
        logger.warning("读取 saved cookies 登录状态失败: {}", exc)
        return AuthSessionResponse(authenticated=False, session_id=None, user=None, cookie_source=None)

    if not result.get("authenticated"):
        return AuthSessionResponse(authenticated=False)

    return AuthSessionResponse(
        authenticated=True,
        user=_to_user_info(result["user"]),
        cookie_source="saved",
    )


@router.get("/session/{session_id}", response_model=AuthSessionResponse)
async def get_session_info(session_id: str) -> AuthSessionResponse:
    """Fetch a specific app session."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(404, "会话不存在或已失效", error_code="SESSION_NOT_FOUND")

    return AuthSessionResponse(
        authenticated=True,
        session_id=session_id,
        user=_to_user_info(session["user_info"]),
        cookie_source=session.get("cookie_source"),
    )


@router.post("/logout")
async def logout(request: LogoutRequest, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Invalidate one application session."""
    login_sessions.pop(request.session_id, None)

    result = await db.execute(select(UserSession).where(UserSession.session_id == request.session_id))
    db_session = result.scalar_one_or_none()
    if db_session:
        db_session.is_valid = False
        db_session.last_active_at = utc_now()
        await db.commit()

    return {"message": "已退出登录"}


async def get_session(session_id: str) -> dict | None:
    """Internal helper used by other routers."""
    if session_id in login_sessions:
        return login_sessions[session_id]

    async with get_db_context() as db:
        result = await db.execute(select(UserSession).where(UserSession.session_id == session_id))
        db_session = result.scalar_one_or_none()

    if not db_session or not db_session.is_valid:
        return None

    service = XhsCliService()
    cookies = service.deserialize_cookies(db_session.cookie_json)
    user_info = {
        "user_id": db_session.xhs_user_id,
        "username": db_session.xhs_username,
        "nickname": db_session.xhs_nickname,
        "avatar": db_session.avatar,
        "ip_location": "",
        "desc": "",
    }
    session = {
        "cookies": cookies,
        "user_info": user_info,
        "cookie_source": "database",
    }
    login_sessions[session_id] = session
    return session
