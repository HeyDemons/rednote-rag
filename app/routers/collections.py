"""
Collection endpoints placeholder.
"""

from fastapi import APIRouter, Query
from loguru import logger

from app.error_handling import raise_api_error
from app.models import CollectionItemsResponse, CollectionSummary, SourceType
from app.routers.auth import get_session
from app.services.xhs_cli_service import XhsCliService


router = APIRouter(prefix="/collections", tags=["collections"])


def _title_for_source(source_type: str) -> str:
    return "我的点赞" if source_type == SourceType.LIKES.value else "我的收藏"


@router.get("/list", response_model=list[CollectionSummary])
async def list_collections(session_id: str = Query(..., description="会话 ID")) -> list[CollectionSummary]:
    """Return logical collections with lightweight counts from the first page."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    service = XhsCliService()
    cookies = session["cookies"]
    user_info = session["user_info"]
    user_id = str(user_info.get("user_id", "")).strip()
    if not user_id:
        raise_api_error(400, "当前会话缺少 user_id", error_code="SESSION_USER_ID_MISSING")

    result: list[CollectionSummary] = []
    for source_type in (SourceType.LIKES.value, SourceType.FAVORITES.value):
        try:
            page = service.list_notes_by_source(source_type, cookies, user_id, cursor="")
            count = None if page["has_more"] else page["count"]
        except Exception as exc:
            logger.warning("加载 collection 首屏计数失败 [{}]: {}", source_type, exc)
            count = None
        result.append(
            CollectionSummary(
                source_type=source_type,
                title=_title_for_source(source_type),
                item_count=count,
                is_selected=True,
            )
        )
    return result


@router.get("/{source_type}/items", response_model=CollectionItemsResponse)
async def list_collection_items(
    source_type: SourceType,
    session_id: str = Query(..., description="会话 ID"),
    cursor: str = Query("", description="分页 cursor"),
) -> CollectionItemsResponse:
    """Return one page of liked or favorited notes."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    service = XhsCliService()
    cookies = session["cookies"]
    user_info = session["user_info"]
    user_id = str(user_info.get("user_id", "")).strip()
    if not user_id:
        raise_api_error(400, "当前会话缺少 user_id", error_code="SESSION_USER_ID_MISSING")

    try:
        page = service.list_notes_by_source(source_type.value, cookies, user_id, cursor=cursor)
    except Exception as exc:
        logger.exception("读取 collection 失败 [{}] cursor={}", source_type.value, cursor)
        raise_api_error(500, f"读取 {source_type.value} 失败", error_code="COLLECTION_FETCH_FAILED")

    return CollectionItemsResponse(
        source_type=source_type.value,
        items=page["items"],
        cursor=page["cursor"],
        has_more=page["has_more"],
        count=page["count"],
    )
