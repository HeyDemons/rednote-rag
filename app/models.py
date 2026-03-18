"""
Database and API models for rednote-rag.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.time_utils import utc_now


class Base(DeclarativeBase):
    """Base declarative model."""


class UserSession(Base):
    """Persisted user login session."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    xhs_user_id: Mapped[str] = mapped_column(String(64), index=True)
    xhs_username: Mapped[str] = mapped_column(String(128), default="")
    xhs_nickname: Mapped[str] = mapped_column(String(128), default="")
    avatar: Mapped[str] = mapped_column(String(1024), default="")
    cookie_json: Mapped[str] = mapped_column(Text)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class NoteCache(Base):
    """Cached normalized Xiaohongshu note detail."""

    __tablename__ = "note_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    normalized_content: Mapped[str] = mapped_column(Text, default="")
    content_source: Mapped[str] = mapped_column(String(64), default="note_detail")
    note_type: Mapped[str] = mapped_column(String(32), default="image")
    author_id: Mapped[str] = mapped_column(String(64), default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    author_avatar: Mapped[str] = mapped_column(String(1024), default="")
    liked_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    ocr_status: Mapped[str] = mapped_column(String(32), default="not_run")
    ocr_image_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    images_json: Mapped[str] = mapped_column(Text, default="[]")
    note_url: Mapped[str] = mapped_column(String(2048), default="")
    xsec_token: Mapped[str] = mapped_column(String(512), default="")
    source_type: Mapped[str] = mapped_column(String(32), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_crawled_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    process_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SourceCollection(Base):
    """Logical remote source collection snapshot for one session."""

    __tablename__ = "source_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_owner_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(128), default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class CollectionItemRecord(Base):
    """One note membership in a logical source collection."""

    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(Integer, index=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    note_type: Mapped[str] = mapped_column(String(32), default="image")
    cover_url: Mapped[str] = mapped_column(String(2048), default="")
    note_url: Mapped[str] = mapped_column(String(2048), default="")
    xsec_token: Mapped[str] = mapped_column(String(512), default="")
    liked_count: Mapped[int] = mapped_column(Integer, default=0)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SyncTaskRecord(Base):
    """Persisted background sync task state."""

    __tablename__ = "sync_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32), default="sync", index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    source_types_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str] = mapped_column(String(256), default="等待开始")
    total_remote_notes: Mapped[int] = mapped_column(Integer, default=0)
    total_candidate_notes: Mapped[int] = mapped_column(Integer, default=0)
    processed_notes: Mapped[int] = mapped_column(Integer, default=0)
    added_notes: Mapped[int] = mapped_column(Integer, default=0)
    updated_notes: Mapped[int] = mapped_column(Integer, default=0)
    removed_notes: Mapped[int] = mapped_column(Integer, default=0)
    skipped_notes: Mapped[int] = mapped_column(Integer, default=0)
    indexed_notes: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    failed_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SourceType(str, Enum):
    """Logical source collections supported by the product."""

    LIKES = "likes"
    FAVORITES = "favorites"


class SessionUserInfo(BaseModel):
    """Normalized authenticated user info returned by auth endpoints."""

    user_id: str
    username: str = ""
    nickname: str
    avatar: str = ""
    ip_location: str = ""
    desc: str = ""


class BrowserLoginRequest(BaseModel):
    """Request body for browser-based login."""

    cookie_source: str = "auto"
    force_refresh: bool = True


class AuthSessionResponse(BaseModel):
    """Response payload for authenticated session state."""

    authenticated: bool
    session_id: str | None = None
    user: SessionUserInfo | None = None
    cookie_source: str | None = None


class QrLoginStartResponse(BaseModel):
    """Response for starting a QR-code login flow."""

    login_id: str
    qr_url: str
    expires_in_seconds: int = 240
    status: str = "waiting"


class QrLoginStatusResponse(BaseModel):
    """Response for polling a QR-code login flow."""

    login_id: str
    status: str
    authenticated: bool = False
    session_id: str | None = None
    user: SessionUserInfo | None = None
    cookie_source: str | None = None
    expires_in_seconds: int = 240
    message: str = ""


class CollectionSummary(BaseModel):
    """Logical source collection summary."""

    source_type: str
    title: str
    item_count: int | None = None
    is_selected: bool = True


class CollectionItem(BaseModel):
    """Normalized note summary for likes/favorites pages."""

    note_id: str
    title: str
    author: str = ""
    note_type: str = "image"
    liked_count: int = 0
    cover_url: str = ""
    note_url: str = ""
    xsec_token: str = ""
    published_at: int | None = None


class CollectionItemsResponse(BaseModel):
    """Paged response for collection note listing."""

    source_type: str
    items: list[CollectionItem]
    cursor: str = ""
    has_more: bool = False
    count: int = 0


class NoteDetail(BaseModel):
    """Normalized note detail payload."""

    note_id: str
    title: str
    content: str = ""
    normalized_content: str = ""
    content_source: str = "note_detail"
    note_type: str = "image"
    author_id: str = ""
    author_name: str = ""
    author_avatar: str = ""
    liked_count: int = 0
    collected_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    image_count: int = 0
    ocr_text: str = ""
    ocr_status: str = "not_run"
    ocr_image_count: int = 0
    ocr_updated_at: datetime | None = None
    tags: list[str] = []
    images: list[str] = []
    note_url: str = ""
    xsec_token: str = ""
    source_type: str = ""
    published_at: datetime | None = None
    last_crawled_at: datetime | None = None
    process_error: str = ""


class CacheNoteRequest(BaseModel):
    """Request to fetch and cache a note detail."""

    source_type: SourceType | None = None
    xsec_token: str = ""
    note_url: str = ""
    force_refresh: bool = True


class CachedNoteResponse(BaseModel):
    """Response for cached note detail."""

    cached: bool
    note: NoteDetail


class ExtractedContentResponse(BaseModel):
    """Response for normalized content extraction preview."""

    note_id: str
    title: str
    content_source: str
    normalized_content: str
    content_length: int
    sufficient_for_indexing: bool


class NoteOcrResponse(BaseModel):
    """Response for OCR preview/debugging."""

    note_id: str
    title: str
    note_type: str = "image"
    ocr_status: str = "not_run"
    ocr_image_count: int = 0
    ocr_updated_at: datetime | None = None
    ocr_text: str = ""
    ocr_text_length: int = 0
    cleaned_ocr_text: str = ""
    cleaned_ocr_text_length: int = 0
    content_source: str = "note_detail"


class IndexNotesRequest(BaseModel):
    """Request to build vector index from cached notes."""

    note_ids: list[str] | None = None
    source_type: SourceType | None = None
    force_reindex: bool = False


class IndexNotesResponse(BaseModel):
    """Index build result."""

    total_notes: int
    indexed_notes: int
    skipped_notes: int
    total_chunks: int
    failed_notes: list[str] = []


class SyncKnowledgeRequest(BaseModel):
    """Request to incrementally sync remote likes/favorites into cache and index."""

    source_type: SourceType | None = None
    max_items_per_source: int = 50
    force_refresh: bool = False
    force_reindex: bool = False


class SyncKnowledgeStartResponse(BaseModel):
    """Response returned when a sync task is created."""

    task_id: str
    message: str


class SyncTaskStatusResponse(BaseModel):
    """Background sync task status."""

    task_id: str
    task_type: str = "sync"
    status: str
    progress: int = 0
    current_step: str = ""
    source_types: list[str] = []
    total_remote_notes: int = 0
    total_candidate_notes: int = 0
    processed_notes: int = 0
    added_notes: int = 0
    updated_notes: int = 0
    removed_notes: int = 0
    skipped_notes: int = 0
    indexed_notes: int = 0
    total_chunks: int = 0
    failed_notes: list[str] = []
    message: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None


class IndexTaskStartResponse(BaseModel):
    """Response returned when an index task is created."""

    task_id: str
    message: str


class SearchRequest(BaseModel):
    """Semantic search request."""

    query: str
    k: int = 5
    note_ids: list[str] | None = None
    source_type: SourceType | None = None


class SearchHit(BaseModel):
    """One semantic search hit."""

    note_id: str
    title: str
    author_name: str = ""
    source_type: str = ""
    content_source: str = ""
    note_url: str = ""
    chunk_index: int = 0
    score: float = 0.0
    snippet: str


class SearchResponse(BaseModel):
    """Semantic search response."""

    query: str
    hits: list[SearchHit]


class ChatRequest(BaseModel):
    """RAG chat request."""

    question: str
    k: int = 5
    note_ids: list[str] | None = None
    source_type: SourceType | None = None


class ChatSearchHit(BaseModel):
    """One deduplicated retrieval hit for chat-centric search UIs."""

    note_id: str
    title: str
    author_name: str = ""
    source_type: str = ""
    content_source: str = ""
    note_url: str = ""
    score: float = 0.0
    chunk_count: int = 0
    snippet: str


class ChatSearchResponse(BaseModel):
    """Search response tailored for chat/source preview UIs."""

    question: str
    hits: list[ChatSearchHit]


class ChatSource(BaseModel):
    """One cited source in the final answer."""

    note_id: str
    title: str
    author_name: str = ""
    source_type: str = ""
    content_source: str = ""
    note_url: str = ""
    snippet: str


class ChatResponse(BaseModel):
    """RAG answer with sources."""

    question: str
    answer: str
    sources: list[ChatSource]


class ChatStreamEvent(BaseModel):
    """One SSE event payload for streaming chat."""

    type: str
    question: str | None = None
    stage: str | None = None
    delta: str | None = None
    answer: str | None = None
    sources: list[ChatSource] = []
    error: str | None = None


class KnowledgeStatusResponse(BaseModel):
    """Knowledge base status summary."""

    cached_notes: int
    indexed_notes: int
    total_indexed_chunks: int


class LogoutRequest(BaseModel):
    """Request body for logout endpoint."""

    session_id: str
