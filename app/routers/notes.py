"""
Note detail fetch and cache endpoints.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.error_handling import raise_api_error
from app.models import (
    CacheNoteRequest,
    CachedNoteResponse,
    ExtractedContentResponse,
    NoteCache,
    NoteDetail,
    NoteOcrResponse,
)
from app.routers.auth import get_session
from app.services.content_fetcher import ContentFetcher
from app.services.ocr import OCRService
from app.services.xhs_cli_service import XhsCliService
from app.time_utils import utc_now


router = APIRouter(prefix="/notes", tags=["notes"])


def _cache_to_detail(cache: NoteCache) -> NoteDetail:
    return NoteDetail(
        note_id=cache.note_id,
        title=cache.title,
        content=cache.content,
        normalized_content=cache.normalized_content,
        content_source=cache.content_source,
        note_type=cache.note_type,
        author_id=cache.author_id,
        author_name=cache.author_name,
        author_avatar=cache.author_avatar,
        liked_count=cache.liked_count,
        collected_count=cache.collected_count,
        comment_count=cache.comment_count,
        share_count=cache.share_count,
        image_count=cache.image_count,
        ocr_text=cache.ocr_text,
        ocr_status=cache.ocr_status,
        ocr_image_count=cache.ocr_image_count,
        ocr_updated_at=cache.ocr_updated_at,
        tags=json.loads(cache.tags_json or "[]"),
        images=json.loads(cache.images_json or "[]"),
        note_url=cache.note_url,
        xsec_token=cache.xsec_token,
        source_type=cache.source_type,
        published_at=cache.published_at,
        last_crawled_at=cache.last_crawled_at,
        process_error=cache.process_error,
    )


async def _get_cached_note(db: AsyncSession, note_id: str) -> NoteCache | None:
    result = await db.execute(select(NoteCache).where(NoteCache.note_id == note_id))
    return result.scalar_one_or_none()


async def _upsert_note_cache(
    db: AsyncSession,
    detail: dict,
) -> NoteCache:
    cache = await _get_cached_note(db, detail["note_id"])
    now = utc_now()
    if cache is None:
        cache = NoteCache(note_id=detail["note_id"], created_at=now)
        db.add(cache)

    cache.title = detail["title"]
    cache.content = detail["content"]
    cache.normalized_content = detail["normalized_content"]
    cache.content_source = detail["content_source"]
    cache.note_type = detail["note_type"]
    cache.author_id = detail["author_id"]
    cache.author_name = detail["author_name"]
    cache.author_avatar = detail["author_avatar"]
    cache.liked_count = detail["liked_count"]
    cache.collected_count = detail["collected_count"]
    cache.comment_count = detail["comment_count"]
    cache.share_count = detail["share_count"]
    cache.image_count = detail["image_count"]
    cache.ocr_text = detail.get("ocr_text", "")
    cache.ocr_status = detail.get("ocr_status", "not_run")
    cache.ocr_image_count = int(detail.get("ocr_image_count") or 0)
    cache.ocr_updated_at = now if cache.ocr_status not in {"not_run", "disabled", "unconfigured"} else None
    cache.tags_json = json.dumps(detail["tags"], ensure_ascii=False)
    cache.images_json = json.dumps(detail["images"], ensure_ascii=False)
    cache.note_url = detail["note_url"]
    cache.xsec_token = detail["xsec_token"]
    cache.source_type = detail["source_type"]
    cache.published_at = detail["published_at"]
    cache.last_crawled_at = now
    cache.raw_json = json.dumps(detail["raw"], ensure_ascii=False)
    cache.process_error = ""
    cache.updated_at = now
    await db.commit()
    await db.refresh(cache)
    return cache


@router.get("/{note_id}", response_model=CachedNoteResponse)
async def get_note_detail(
    note_id: str,
    session_id: str = Query(..., description="会话 ID"),
    force_refresh: bool = Query(False, description="是否强制重新抓取"),
    db: AsyncSession = Depends(get_db),
) -> CachedNoteResponse:
    """Fetch one note detail from cache or remote provider."""
    if not force_refresh:
        cached = await _get_cached_note(db, note_id)
        if cached:
            return CachedNoteResponse(cached=True, note=_cache_to_detail(cached))

    raise_api_error(404, "缓存中不存在该 note，请调用缓存接口抓取", error_code="NOTE_CACHE_MISS")


@router.post("/{note_id}/cache", response_model=CachedNoteResponse)
async def cache_note_detail(
    note_id: str,
    payload: CacheNoteRequest,
    session_id: str = Query(..., description="会话 ID"),
    db: AsyncSession = Depends(get_db),
) -> CachedNoteResponse:
    """Fetch one note detail from Xiaohongshu and upsert it into local cache."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    service = XhsCliService()
    content_fetcher = ContentFetcher()
    ocr_service = OCRService()
    cookies = session["cookies"]

    try:
        detail = service.fetch_note_detail(
            cookies=cookies,
            note_id=note_id,
            xsec_token=payload.xsec_token,
            source_type=payload.source_type.value if payload.source_type else "",
            note_url=payload.note_url,
        )
        detail.update(ocr_service.extract_note_ocr(detail))
        detail.update(content_fetcher.build_note_content(detail))
    except Exception as exc:
        cached = await _get_cached_note(db, note_id)
        if cached:
            cached.process_error = str(exc)
            cached.updated_at = utc_now()
            await db.commit()
        logger.exception("抓取 note 详情失败 [{}]", note_id)
        raise_api_error(500, "抓取 note 详情失败", error_code="NOTE_FETCH_FAILED")

    cache = await _upsert_note_cache(db, detail)
    return CachedNoteResponse(cached=False, note=_cache_to_detail(cache))


@router.get("/{note_id}/content", response_model=ExtractedContentResponse)
async def get_note_extracted_content(
    note_id: str,
    session_id: str = Query(..., description="会话 ID"),
    db: AsyncSession = Depends(get_db),
) -> ExtractedContentResponse:
    """Preview the normalized indexing text for one cached note."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    cached = await _get_cached_note(db, note_id)
    if not cached:
        raise_api_error(404, "缓存中不存在该 note，请先抓取", error_code="NOTE_CACHE_MISS")

    return ExtractedContentResponse(
        note_id=cached.note_id,
        title=cached.title,
        content_source=cached.content_source,
        normalized_content=cached.normalized_content,
        content_length=len(cached.normalized_content or ""),
        sufficient_for_indexing=len(cached.normalized_content or "") >= ContentFetcher.MIN_CONTENT_LENGTH,
    )


@router.get("/{note_id}/ocr", response_model=NoteOcrResponse)
async def get_note_ocr_preview(
    note_id: str,
    session_id: str = Query(..., description="会话 ID"),
    db: AsyncSession = Depends(get_db),
) -> NoteOcrResponse:
    """Preview cached OCR output for one note."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    cached = await _get_cached_note(db, note_id)
    if not cached:
        raise_api_error(404, "缓存中不存在该 note，请先抓取", error_code="NOTE_CACHE_MISS")

    cleaned_ocr_text = ContentFetcher._clean_ocr_text(
        cached.ocr_text or "",
        title=cached.title or "",
        raw_content=cached.content or "",
        tags=json.loads(cached.tags_json or "[]"),
        author_name=cached.author_name or "",
    )

    return NoteOcrResponse(
        note_id=cached.note_id,
        title=cached.title,
        note_type=cached.note_type,
        ocr_status=cached.ocr_status,
        ocr_image_count=cached.ocr_image_count,
        ocr_updated_at=cached.ocr_updated_at,
        ocr_text=cached.ocr_text or "",
        ocr_text_length=len(cached.ocr_text or ""),
        cleaned_ocr_text=cleaned_ocr_text,
        cleaned_ocr_text_length=len(cleaned_ocr_text),
        content_source=cached.content_source,
    )
