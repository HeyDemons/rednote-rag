"""
Shared API error helpers and exception handlers.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger


def error_payload(
    *,
    message: str,
    error_code: str,
    path: str,
    details: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "detail": message,
        "error_code": error_code,
        "path": path,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if details is not None:
        payload["details"] = details
    return payload


def raise_api_error(status_code: int, message: str, *, error_code: str) -> None:
    raise HTTPException(status_code=status_code, detail={"message": message, "error_code": error_code})


def _extract_http_exception(exc: HTTPException) -> tuple[str, str, Any | None]:
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "请求失败")
        error_code = str(detail.get("error_code") or f"HTTP_{exc.status_code}")
        details = detail.get("details")
        return message, error_code, details
    return str(detail), f"HTTP_{exc.status_code}", None


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    message, error_code, details = _extract_http_exception(exc)
    if exc.status_code >= 500:
        logger.error(
            "HTTPException {} {} -> {} {} | {}",
            request.method,
            request.url.path,
            exc.status_code,
            error_code,
            message,
        )
    else:
        logger.warning(
            "HTTPException {} {} -> {} {} | {}",
            request.method,
            request.url.path,
            exc.status_code,
            error_code,
            message,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            message=message,
            error_code=error_code,
            path=request.url.path,
            details=details,
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("ValidationError {} {} | {}", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content=error_payload(
            message="请求参数不合法",
            error_code="VALIDATION_ERROR",
            path=request.url.path,
            details=exc.errors(),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("UnhandledException {} {}", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload(
            message="服务器内部错误，请查看日志",
            error_code="INTERNAL_SERVER_ERROR",
            path=request.url.path,
        ),
    )
