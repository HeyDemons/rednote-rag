"""
Vector indexing and semantic search endpoints.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_context
from app.error_handling import raise_api_error
from app.models import (
    CollectionItemRecord,
    IndexTaskStartResponse,
    IndexNotesRequest,
    IndexNotesResponse,
    KnowledgeStatusResponse,
    NoteCache,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SourceCollection,
    SyncTaskRecord,
    SyncKnowledgeRequest,
    SyncKnowledgeStartResponse,
    SyncTaskStatusResponse,
)
from app.routers.auth import get_session
from app.routers.notes import _get_cached_note, _upsert_note_cache
from app.services.content_fetcher import ContentFetcher
from app.services.ocr import OCRService
from app.services.rag import RAGService
from app.services.xhs_cli_service import XhsCliService
from app.time_utils import utc_now


router = APIRouter(prefix="/knowledge", tags=["knowledge"])
_rag_service: RAGService | None = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def _raise_knowledge_error(exc: Exception) -> None:
    message = str(exc)
    if "embedding" in message.lower() or "OPENAI_API_KEY" in message or "EMBEDDING_MODEL" in message:
        raise_api_error(400, message, error_code="EMBEDDING_CONFIG_INVALID")
    logger.exception("知识库处理失败")
    raise_api_error(500, "知识库处理失败", error_code="KNOWLEDGE_PIPELINE_FAILED")


def _serialize_sync_task(record: SyncTaskRecord) -> dict[str, Any]:
    try:
        source_types = json.loads(record.source_types_json or "[]")
    except json.JSONDecodeError:
        source_types = []
    try:
        failed_notes = json.loads(record.failed_notes_json or "[]")
    except json.JSONDecodeError:
        failed_notes = []

    return {
        "task_id": record.task_id,
        "task_type": record.task_type,
        "status": record.status,
        "progress": record.progress,
        "current_step": record.current_step,
        "source_types": source_types if isinstance(source_types, list) else [],
        "total_remote_notes": record.total_remote_notes,
        "total_candidate_notes": record.total_candidate_notes,
        "processed_notes": record.processed_notes,
        "added_notes": record.added_notes,
        "updated_notes": record.updated_notes,
        "removed_notes": record.removed_notes,
        "skipped_notes": record.skipped_notes,
        "indexed_notes": record.indexed_notes,
        "total_chunks": record.total_chunks,
        "failed_notes": failed_notes if isinstance(failed_notes, list) else [],
        "message": record.message,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
    }


async def _create_sync_task(
    task_id: str,
    *,
    session_id: str,
    source_types: list[str],
    task_type: str = "sync",
) -> None:
    now = utc_now()
    async with get_db_context() as db:
        record = SyncTaskRecord(
            task_id=task_id,
            task_type=task_type,
            session_id=session_id,
            source_types_json=json.dumps(source_types, ensure_ascii=False),
            status="pending",
            progress=0,
            current_step="等待开始",
            total_remote_notes=0,
            total_candidate_notes=0,
            processed_notes=0,
            added_notes=0,
            updated_notes=0,
            removed_notes=0,
            skipped_notes=0,
            indexed_notes=0,
            total_chunks=0,
            failed_notes_json="[]",
            message="",
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        await db.commit()


async def _update_sync_task(task_id: str, **fields: Any) -> None:
    async with get_db_context() as db:
        result = await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
        record = result.scalar_one_or_none()
        if record is None:
            return

        if "source_types" in fields:
            record.source_types_json = json.dumps(fields.pop("source_types"), ensure_ascii=False)
        if "failed_notes" in fields:
            record.failed_notes_json = json.dumps(fields.pop("failed_notes"), ensure_ascii=False)

        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = utc_now()
        await db.commit()


async def _get_task_record(task_id: str) -> SyncTaskRecord:
    async with get_db_context() as db:
        result = await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
        record = result.scalar_one_or_none()
    if record is None:
        raise_api_error(404, "任务不存在", error_code="SYNC_TASK_NOT_FOUND")
    return record


async def _task_response(task_id: str) -> SyncTaskStatusResponse:
    record = await _get_task_record(task_id)
    return SyncTaskStatusResponse(**_serialize_sync_task(record))


def _merge_remote_item(
    merged: dict[str, dict[str, Any]],
    item: dict[str, Any],
) -> None:
    note_id = str(item.get("note_id") or "").strip()
    if not note_id:
        return

    existing = merged.get(note_id)
    if existing is None:
        merged[note_id] = item
        return

    existing_source = str(existing.get("source_type") or "")
    current_source = str(item.get("source_type") or "")
    if existing_source != "favorites" and current_source == "favorites":
        merged[note_id] = item


def _build_index_payload(note: NoteCache) -> dict[str, Any]:
    return {
        "note_id": note.note_id,
        "title": note.title,
        "normalized_content": note.normalized_content,
        "author_name": note.author_name,
        "source_type": note.source_type,
        "content_source": note.content_source,
        "note_url": note.note_url,
    }


async def _list_remote_notes(
    service: XhsCliService,
    *,
    cookies: dict[str, str],
    user_id: str,
    source_type: str,
    max_items: int,
) -> list[dict[str, Any]]:
    cursor = ""
    collected: list[dict[str, Any]] = []

    while True:
        page = service.list_notes_by_source(
            source_type,
            cookies=cookies,
            user_id=user_id,
            cursor=cursor,
        )
        items = list(page.get("items", []))
        collected.extend(items)
        if max_items > 0 and len(collected) >= max_items:
            return collected[:max_items]
        if not page.get("has_more"):
            return collected
        cursor = str(page.get("cursor") or "")
        if not cursor:
            return collected


async def _ensure_source_collection(
    db: AsyncSession,
    *,
    session_id: str,
    source_type: str,
    user_id: str,
) -> SourceCollection:
    result = await db.execute(
        select(SourceCollection).where(
            SourceCollection.session_id == session_id,
            SourceCollection.source_type == source_type,
        )
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        collection = SourceCollection(
            session_id=session_id,
            source_type=source_type,
            source_owner_id=user_id,
            title="我的点赞" if source_type == "likes" else "我的收藏",
            is_selected=True,
            created_at=utc_now(),
        )
        db.add(collection)
        await db.flush()
    return collection


async def _resolve_sync_limit(
    db: AsyncSession,
    *,
    session_id: str,
    source_type: str,
    requested_max: int,
) -> int:
    """Use full sync on first run for a source, then fall back to incremental sync."""
    result = await db.execute(
        select(SourceCollection).where(
            SourceCollection.session_id == session_id,
            SourceCollection.source_type == source_type,
        )
    )
    collection = result.scalar_one_or_none()
    if collection is None or collection.last_sync_at is None:
        return 0
    return requested_max


async def _sync_collection_snapshot(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    source_type: str,
    items: list[dict[str, Any]],
) -> int:
    collection = await _ensure_source_collection(
        db,
        session_id=session_id,
        source_type=source_type,
        user_id=user_id,
    )
    now = utc_now()
    collection.item_count = len(items)
    collection.last_sync_at = now
    collection.updated_at = now

    result = await db.execute(
        select(CollectionItemRecord).where(CollectionItemRecord.collection_id == collection.id)
    )
    existing_items = {item.note_id: item for item in result.scalars().all()}
    current_note_ids = {str(item.get("note_id") or "").strip() for item in items if str(item.get("note_id") or "").strip()}

    for item in items:
        note_id = str(item.get("note_id") or "").strip()
        if not note_id:
            continue
        record = existing_items.get(note_id)
        if record is None:
            record = CollectionItemRecord(
                collection_id=collection.id,
                note_id=note_id,
                created_at=now,
            )
            db.add(record)

        record.source_type = source_type
        record.title = str(item.get("title") or "")
        record.author_name = str(item.get("author") or "")
        record.note_type = str(item.get("note_type") or "image")
        record.cover_url = str(item.get("cover_url") or "")
        record.note_url = str(item.get("note_url") or "")
        record.xsec_token = str(item.get("xsec_token") or "")
        record.liked_count = int(item.get("liked_count") or 0)
        record.is_selected = True
        record.is_active = True
        record.last_seen_at = now
        record.removed_at = None
        record.updated_at = now

    removed_count = 0
    for note_id, record in existing_items.items():
        if note_id in current_note_ids or not record.is_active:
            continue
        record.is_active = False
        record.removed_at = now
        record.updated_at = now
        removed_count += 1

    await db.commit()
    return removed_count


async def _resolve_retry_candidates(
    db: AsyncSession,
    *,
    session_id: str,
    note_ids: list[str],
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(CollectionItemRecord, SourceCollection)
        .join(SourceCollection, SourceCollection.id == CollectionItemRecord.collection_id)
        .where(
            SourceCollection.session_id == session_id,
            CollectionItemRecord.note_id.in_(note_ids),
            CollectionItemRecord.is_active.is_(True),
        )
    )

    retry_items: dict[str, dict[str, Any]] = {}
    for record, _collection in result.all():
        existing = retry_items.get(record.note_id)
        current = {
            "note_id": record.note_id,
            "title": record.title,
            "author": record.author_name,
            "note_type": record.note_type,
            "cover_url": record.cover_url,
            "note_url": record.note_url,
            "xsec_token": record.xsec_token,
            "liked_count": record.liked_count,
            "source_type": record.source_type,
        }
        if existing is None:
            retry_items[record.note_id] = current
            continue
        if existing.get("source_type") != "favorites" and current.get("source_type") == "favorites":
            retry_items[record.note_id] = current
    return list(retry_items.values())


async def _sync_notes_task(
    task_id: str,
    *,
    session_id: str,
    payload: SyncKnowledgeRequest,
    retry_items: list[dict[str, Any]] | None = None,
) -> None:
    try:
        await _update_sync_task(task_id, status="running", current_step="加载会话")
        session = await get_session(session_id)
        if not session:
            raise RuntimeError("未登录或会话已失效")

        cookies = session["cookies"]
        user_id = str(session["user_info"].get("user_id") or "").strip()
        if not user_id:
            raise RuntimeError("当前会话缺少 user_id")

        service = XhsCliService()
        content_fetcher = ContentFetcher()
        ocr_service = OCRService()
        rag = get_rag_service()
        skip_ocr_for_bulk_sync = retry_items is None and payload.max_items_per_source == 0

        source_types = [payload.source_type.value] if payload.source_type else ["likes", "favorites"]
        source_items_map: dict[str, list[dict[str, Any]]] = {}
        merged_remote_items: dict[str, dict[str, Any]] = {}
        removed_notes = 0

        if retry_items is None:
            for source_type in source_types:
                await _update_sync_task(task_id, current_step=f"拉取 {source_type} 列表")
                async with get_db_context() as db:
                    effective_max_items = await _resolve_sync_limit(
                        db,
                        session_id=session_id,
                        source_type=source_type,
                        requested_max=payload.max_items_per_source,
                    )
                items = await _list_remote_notes(
                    service,
                    cookies=cookies,
                    user_id=user_id,
                    source_type=source_type,
                    max_items=effective_max_items,
                )
                source_items_map[source_type] = items
                async with get_db_context() as db:
                    removed_notes += await _sync_collection_snapshot(
                        db,
                        session_id=session_id,
                        user_id=user_id,
                        source_type=source_type,
                        items=items,
                    )
                for item in items:
                    _merge_remote_item(merged_remote_items, item)
            remote_items = list(merged_remote_items.values())
        else:
            remote_items = retry_items

        await _update_sync_task(task_id, total_remote_notes=len(remote_items), current_step="比对本地缓存")

        async with get_db_context() as db:
            existing_result = await db.execute(
                select(NoteCache).where(NoteCache.note_id.in_([item["note_id"] for item in remote_items]))
            )
            existing_notes = {note.note_id: note for note in existing_result.scalars().all()}

        candidate_items: list[dict[str, Any]] = []
        skipped_notes = 0
        for item in remote_items:
            cached = existing_notes.get(item["note_id"])
            if cached is None:
                candidate_items.append(item)
                continue

            source_changed = bool(item.get("source_type")) and cached.source_type != str(item.get("source_type") or "")
            if payload.force_refresh or source_changed:
                candidate_items.append(item)
            else:
                skipped_notes += 1

        await _update_sync_task(
            task_id,
            total_candidate_notes=len(candidate_items),
            removed_notes=removed_notes,
            skipped_notes=skipped_notes,
            current_step="开始抓取 note 详情",
        )

        if not candidate_items:
            await _update_sync_task(
                task_id,
                status="completed",
                progress=100,
                message="没有需要同步的新内容",
                completed_at=utc_now(),
                current_step="完成",
                removed_notes=removed_notes,
            )
            return

        indexed_notes = 0
        total_chunks = 0
        added_notes = 0
        updated_notes = 0
        failed_notes: list[str] = []

        for idx, item in enumerate(candidate_items, start=1):
            note_id = str(item.get("note_id") or "").strip()
            await _update_sync_task(
                task_id,
                current_step=f"处理 note {note_id}",
                processed_notes=idx - 1,
                progress=int(((idx - 1) / len(candidate_items)) * 100),
            )
            try:
                detail = service.fetch_note_detail(
                    cookies=cookies,
                    note_id=note_id,
                    xsec_token=str(item.get("xsec_token") or ""),
                    source_type=str(item.get("source_type") or ""),
                    note_url=str(item.get("note_url") or ""),
                )
                if skip_ocr_for_bulk_sync:
                    detail.update(
                        {
                            "ocr_text": "",
                            "ocr_status": "skipped_bulk_sync",
                            "ocr_image_count": 0,
                        }
                    )
                else:
                    detail.update(ocr_service.extract_note_ocr(detail))
                detail.update(content_fetcher.build_note_content(detail))

                async with get_db_context() as db:
                    existed_before = await _get_cached_note(db, note_id)
                    cache = await _upsert_note_cache(db, detail)
                    if existed_before is None:
                        added_notes += 1
                    else:
                        updated_notes += 1

                    should_index = bool((cache.normalized_content or "").strip()) and (
                        payload.force_refresh or payload.force_reindex or not cache.is_indexed
                    )
                    if should_index:
                        chunks = rag.index_note(
                            _build_index_payload(cache),
                            force_reindex=payload.force_refresh or payload.force_reindex,
                        )
                        cache.is_indexed = chunks > 0
                        cache.indexed_chunks = chunks
                        cache.indexed_at = utc_now() if chunks > 0 else None
                        await db.commit()
                        if chunks > 0:
                            indexed_notes += 1
                            total_chunks += chunks
            except Exception as exc:
                logger.exception("同步 note 失败 [{}]", note_id)
                failed_notes.append(note_id)

            await _update_sync_task(
                task_id,
                processed_notes=idx,
                added_notes=added_notes,
                updated_notes=updated_notes,
                removed_notes=removed_notes,
                indexed_notes=indexed_notes,
                total_chunks=total_chunks,
                failed_notes=failed_notes,
                progress=int((idx / len(candidate_items)) * 100),
            )

        status = "completed" if not failed_notes else "completed"
        message = (
            f"同步完成：新增 {added_notes}，更新 {updated_notes}，移除 {removed_notes}，"
            f"跳过 {skipped_notes}，失败 {len(failed_notes)}"
        )
        await _update_sync_task(
            task_id,
            status=status,
            progress=100,
            current_step="完成",
            message=message,
            completed_at=utc_now(),
        )
    except Exception as exc:
        logger.exception("同步任务失败 [{}]", task_id)
        await _update_sync_task(
            task_id,
            status="failed",
            current_step="失败",
            message=str(exc),
            completed_at=utc_now(),
        )


async def _index_notes_task(
    task_id: str,
    *,
    payload: IndexNotesRequest,
    session_id: str,
) -> None:
    try:
        await _update_sync_task(task_id, status="running", current_step="加载会话")
        session = await get_session(session_id)
        if not session:
            raise RuntimeError("未登录或会话已失效")

        async with get_db_context() as db:
            stmt = select(NoteCache)
            if payload.note_ids:
                stmt = stmt.where(NoteCache.note_id.in_(payload.note_ids))
            if payload.source_type:
                stmt = stmt.where(NoteCache.source_type == payload.source_type.value)
            result = await db.execute(stmt)
            notes = list(result.scalars().all())

        await _update_sync_task(
            task_id,
            total_remote_notes=len(notes),
            total_candidate_notes=len(notes),
            current_step="开始建立索引",
        )

        rag = get_rag_service()
        indexed_notes = 0
        skipped_notes = 0
        total_chunks = 0
        failed_notes: list[str] = []

        if not notes:
            await _update_sync_task(
                task_id,
                status="completed",
                progress=100,
                current_step="完成",
                message="没有可索引的 note",
                completed_at=utc_now(),
            )
            return

        for idx, note in enumerate(notes, start=1):
            await _update_sync_task(
                task_id,
                current_step=f"索引 note {note.note_id}",
                processed_notes=idx - 1,
                progress=int(((idx - 1) / len(notes)) * 100),
            )
            normalized_content = (note.normalized_content or "").strip()
            if not normalized_content:
                skipped_notes += 1
            elif note.is_indexed and not payload.force_reindex:
                skipped_notes += 1
            else:
                try:
                    chunks = rag.index_note(_build_index_payload(note), force_reindex=payload.force_reindex)
                    async with get_db_context() as db:
                        current = await _get_cached_note(db, note.note_id)
                        if current is not None:
                            current.is_indexed = chunks > 0
                            current.indexed_chunks = chunks
                            current.indexed_at = utc_now() if chunks > 0 else None
                            await db.commit()
                    indexed_notes += 1 if chunks > 0 else 0
                    skipped_notes += 1 if chunks == 0 else 0
                    total_chunks += chunks
                except Exception:
                    failed_notes.append(note.note_id)

            await _update_sync_task(
                task_id,
                processed_notes=idx,
                skipped_notes=skipped_notes,
                indexed_notes=indexed_notes,
                total_chunks=total_chunks,
                failed_notes=failed_notes,
                progress=int((idx / len(notes)) * 100),
            )

        await _update_sync_task(
            task_id,
            status="completed",
            progress=100,
            current_step="完成",
            message=f"索引完成：成功 {indexed_notes}，跳过 {skipped_notes}，失败 {len(failed_notes)}",
            completed_at=utc_now(),
        )
    except Exception as exc:
        logger.exception("索引任务失败 [{}]", task_id)
        await _update_sync_task(
            task_id,
            status="failed",
            current_step="失败",
            message=str(exc),
            completed_at=utc_now(),
        )


@router.get("/status", response_model=KnowledgeStatusResponse)
async def knowledge_status(
    session_id: str = Query(..., description="会话 ID"),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeStatusResponse:
    """Return cache/index status summary."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    cached_notes = int(await db.scalar(select(func.count()).select_from(NoteCache)) or 0)
    indexed_notes = int(
        await db.scalar(select(func.count()).select_from(NoteCache).where(NoteCache.is_indexed.is_(True))) or 0
    )
    total_indexed_chunks = int(await db.scalar(select(func.sum(NoteCache.indexed_chunks))) or 0)
    return KnowledgeStatusResponse(
        cached_notes=cached_notes,
        indexed_notes=indexed_notes,
        total_indexed_chunks=total_indexed_chunks,
    )


@router.post("/index", response_model=IndexNotesResponse)
async def index_notes(
    payload: IndexNotesRequest,
    session_id: str = Query(..., description="会话 ID"),
    db: AsyncSession = Depends(get_db),
) -> IndexNotesResponse:
    """Build vector index from cached notes."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    stmt = select(NoteCache)
    if payload.note_ids:
        stmt = stmt.where(NoteCache.note_id.in_(payload.note_ids))
    if payload.source_type:
        stmt = stmt.where(NoteCache.source_type == payload.source_type.value)

    result = await db.execute(stmt)
    notes = list(result.scalars().all())
    rag = get_rag_service()

    indexed_notes = 0
    skipped_notes = 0
    total_chunks = 0
    failed_notes: list[str] = []

    for note in notes:
        normalized_content = (note.normalized_content or "").strip()
        if not normalized_content:
            skipped_notes += 1
            continue
        if note.is_indexed and not payload.force_reindex:
            skipped_notes += 1
            continue

        try:
            chunks = rag.index_note(
                {
                    "note_id": note.note_id,
                    "title": note.title,
                    "normalized_content": note.normalized_content,
                    "author_name": note.author_name,
                    "source_type": note.source_type,
                    "content_source": note.content_source,
                    "note_url": note.note_url,
                },
                force_reindex=payload.force_reindex,
            )
            note.is_indexed = chunks > 0
            note.indexed_chunks = chunks
            note.indexed_at = utc_now() if chunks > 0 else None
            indexed_notes += 1 if chunks > 0 else 0
            skipped_notes += 1 if chunks == 0 else 0
            total_chunks += chunks
        except Exception as exc:
            failed_notes.append(note.note_id)
            await db.rollback()
            _raise_knowledge_error(exc)

    await db.commit()
    return IndexNotesResponse(
        total_notes=len(notes),
        indexed_notes=indexed_notes,
        skipped_notes=skipped_notes,
        total_chunks=total_chunks,
        failed_notes=failed_notes,
    )


@router.post("/index/task", response_model=IndexTaskStartResponse)
async def start_index_task(
    payload: IndexNotesRequest,
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="会话 ID"),
) -> IndexTaskStartResponse:
    """Start a background index task for cached notes."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    source_types = [payload.source_type.value] if payload.source_type else []
    task_id = str(uuid.uuid4())
    await _create_sync_task(task_id, session_id=session_id, source_types=source_types, task_type="index")
    background_tasks.add_task(_index_notes_task, task_id, payload=payload, session_id=session_id)
    return IndexTaskStartResponse(task_id=task_id, message="索引任务已启动")


@router.get("/index/status/{task_id}", response_model=SyncTaskStatusResponse)
async def get_index_task_status(task_id: str) -> SyncTaskStatusResponse:
    """Get current background index task status."""
    record = await _get_task_record(task_id)
    if record.task_type != "index":
        raise_api_error(404, "索引任务不存在", error_code="INDEX_TASK_NOT_FOUND")
    return SyncTaskStatusResponse(**_serialize_sync_task(record))


@router.post("/index/retry/{task_id}", response_model=IndexTaskStartResponse)
async def retry_index_failed_notes(
    task_id: str,
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="会话 ID"),
) -> IndexTaskStartResponse:
    """Retry failed notes from a previous index task."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    record = await _get_task_record(task_id)
    if record.task_type != "index":
        raise_api_error(404, "索引任务不存在", error_code="INDEX_TASK_NOT_FOUND")

    task = _serialize_sync_task(record)
    failed_note_ids = list(task.get("failed_notes") or [])
    if not failed_note_ids:
        raise_api_error(400, "原索引任务没有失败项可重试", error_code="INDEX_TASK_NO_FAILED_ITEMS")

    retry_task_id = str(uuid.uuid4())
    source_types = [item for item in list(task.get("source_types") or []) if item]
    await _create_sync_task(
        retry_task_id,
        session_id=session_id,
        source_types=source_types,
        task_type="index",
    )
    background_tasks.add_task(
        _index_notes_task,
        retry_task_id,
        payload=IndexNotesRequest(
            note_ids=failed_note_ids,
            source_type=None,
            force_reindex=True,
        ),
        session_id=session_id,
    )
    return IndexTaskStartResponse(task_id=retry_task_id, message="索引失败项重试任务已启动")


@router.post("/sync", response_model=SyncKnowledgeStartResponse)
async def sync_knowledge(
    payload: SyncKnowledgeRequest,
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="会话 ID"),
) -> SyncKnowledgeStartResponse:
    """Start an incremental sync task for likes/favorites."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    source_types = [payload.source_type.value] if payload.source_type else ["likes", "favorites"]
    task_id = str(uuid.uuid4())
    await _create_sync_task(task_id, session_id=session_id, source_types=source_types)
    background_tasks.add_task(_sync_notes_task, task_id, session_id=session_id, payload=payload)
    return SyncKnowledgeStartResponse(task_id=task_id, message="同步任务已启动")


@router.get("/sync/status/{task_id}", response_model=SyncTaskStatusResponse)
async def get_sync_status(task_id: str) -> SyncTaskStatusResponse:
    """Get current incremental sync task status."""
    return await _task_response(task_id)


@router.post("/sync/retry/{task_id}", response_model=SyncKnowledgeStartResponse)
async def retry_sync_failed_notes(
    task_id: str,
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="会话 ID"),
) -> SyncKnowledgeStartResponse:
    """Retry failed note fetch/index operations from a previous sync task."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    task = _serialize_sync_task(await _get_task_record(task_id))

    failed_note_ids = list(task.get("failed_notes") or [])
    if not failed_note_ids:
        raise_api_error(400, "原任务没有失败项可重试", error_code="SYNC_TASK_NO_FAILED_ITEMS")

    async with get_db_context() as db:
        retry_items = await _resolve_retry_candidates(
            db,
            session_id=session_id,
            note_ids=failed_note_ids,
        )
    if not retry_items:
        raise_api_error(400, "没有可用于重试的有效 collection_item 记录", error_code="RETRY_CANDIDATES_EMPTY")

    payload = SyncKnowledgeRequest(
        source_type=None,
        max_items_per_source=len(retry_items),
        force_refresh=True,
        force_reindex=True,
    )
    retry_task_id = str(uuid.uuid4())
    await _create_sync_task(
        retry_task_id,
        session_id=session_id,
        source_types=list({str(item.get("source_type") or "") for item in retry_items if item.get("source_type")}),
    )
    background_tasks.add_task(
        _sync_notes_task,
        retry_task_id,
        session_id=session_id,
        payload=payload,
        retry_items=retry_items,
    )
    return SyncKnowledgeStartResponse(task_id=retry_task_id, message="失败项重试任务已启动")


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    payload: SearchRequest,
    session_id: str = Query(..., description="会话 ID"),
) -> SearchResponse:
    """Run semantic search on indexed note content."""
    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    rag = get_rag_service()
    try:
        hits = rag.search(
            payload.query,
            k=payload.k,
            note_ids=payload.note_ids,
            source_type=payload.source_type.value if payload.source_type else None,
        )
    except Exception as exc:
        _raise_knowledge_error(exc)
    return SearchResponse(query=payload.query, hits=[SearchHit(**hit) for hit in hits])
