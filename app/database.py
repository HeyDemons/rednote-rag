"""
Async database helpers.
"""

from contextlib import asynccontextmanager
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base


engine = create_async_engine(settings.database_url, echo=settings.sql_echo, future=True)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all configured tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_sqlite_migrations(conn)


async def get_db():
    """FastAPI dependency for database access."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """Async context manager for ad-hoc DB usage."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def _run_sqlite_migrations(conn) -> None:
    """Apply minimal additive migrations for local SQLite development."""
    result = await conn.execute(text("PRAGMA table_info(note_cache)"))
    rows = result.fetchall()
    if rows:
        existing_columns = {row[1] for row in rows}
        additive_columns = {
            "normalized_content": "ALTER TABLE note_cache ADD COLUMN normalized_content TEXT NOT NULL DEFAULT ''",
            "content_source": "ALTER TABLE note_cache ADD COLUMN content_source VARCHAR(64) NOT NULL DEFAULT 'note_detail'",
            "ocr_text": "ALTER TABLE note_cache ADD COLUMN ocr_text TEXT NOT NULL DEFAULT ''",
            "ocr_status": "ALTER TABLE note_cache ADD COLUMN ocr_status VARCHAR(32) NOT NULL DEFAULT 'not_run'",
            "ocr_image_count": "ALTER TABLE note_cache ADD COLUMN ocr_image_count INTEGER NOT NULL DEFAULT 0",
            "ocr_updated_at": "ALTER TABLE note_cache ADD COLUMN ocr_updated_at DATETIME",
            "is_indexed": "ALTER TABLE note_cache ADD COLUMN is_indexed BOOLEAN NOT NULL DEFAULT 0",
            "indexed_chunks": "ALTER TABLE note_cache ADD COLUMN indexed_chunks INTEGER NOT NULL DEFAULT 0",
            "indexed_at": "ALTER TABLE note_cache ADD COLUMN indexed_at DATETIME",
        }

        for column_name, sql in additive_columns.items():
            if column_name not in existing_columns:
                await conn.execute(text(sql))

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS sync_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id VARCHAR(64) NOT NULL UNIQUE,
                session_id VARCHAR(64) NOT NULL,
                source_types_json TEXT NOT NULL DEFAULT '[]',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                current_step VARCHAR(256) NOT NULL DEFAULT '等待开始',
                total_remote_notes INTEGER NOT NULL DEFAULT 0,
                total_candidate_notes INTEGER NOT NULL DEFAULT 0,
                processed_notes INTEGER NOT NULL DEFAULT 0,
                added_notes INTEGER NOT NULL DEFAULT 0,
                updated_notes INTEGER NOT NULL DEFAULT 0,
                removed_notes INTEGER NOT NULL DEFAULT 0,
                skipped_notes INTEGER NOT NULL DEFAULT 0,
                indexed_notes INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                failed_notes_json TEXT NOT NULL DEFAULT '[]',
                message TEXT NOT NULL DEFAULT '',
                started_at DATETIME NOT NULL,
                completed_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    result = await conn.execute(text("PRAGMA table_info(sync_tasks)"))
    sync_rows = result.fetchall()
    if sync_rows:
        sync_columns = {row[1] for row in sync_rows}
        if "task_type" not in sync_columns:
            await conn.execute(
                text("ALTER TABLE sync_tasks ADD COLUMN task_type VARCHAR(32) NOT NULL DEFAULT 'sync'")
            )
