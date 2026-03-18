import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app
from app.database import get_db_context
from app.models import CollectionItemRecord, SourceCollection, SyncTaskRecord
from app.routers.auth import login_sessions
from app.routers.knowledge import (
    _create_sync_task,
    _resolve_retry_candidates,
    _sync_collection_snapshot,
)


class Phase7SyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session_id = f"test-phase7-{uuid.uuid4()}"
        self.user_id = "test-user"
        login_sessions[self.session_id] = {
            "cookies": {"a1": "test-cookie"},
            "user_info": {
                "user_id": self.user_id,
                "username": "tester",
                "nickname": "tester",
                "avatar": "",
                "ip_location": "",
                "desc": "",
            },
            "cookie_source": "test",
        }

    async def asyncTearDown(self) -> None:
        login_sessions.pop(self.session_id, None)
        async with get_db_context() as db:
            await db.execute(
                delete(CollectionItemRecord).where(
                    CollectionItemRecord.collection_id.in_(
                        select(SourceCollection.id).where(SourceCollection.session_id == self.session_id)
                    )
                )
            )
            await db.execute(delete(SourceCollection).where(SourceCollection.session_id == self.session_id))
            await db.execute(delete(SyncTaskRecord).where(SyncTaskRecord.session_id == self.session_id))
            await db.commit()

    async def test_sync_snapshot_marks_removed_items_inactive(self) -> None:
        first_items = [
            {
                "note_id": "n1",
                "title": "A",
                "author": "u1",
                "note_type": "image",
                "cover_url": "",
                "note_url": "url1",
                "xsec_token": "x1",
                "liked_count": 1,
            },
            {
                "note_id": "n2",
                "title": "B",
                "author": "u2",
                "note_type": "image",
                "cover_url": "",
                "note_url": "url2",
                "xsec_token": "x2",
                "liked_count": 2,
            },
        ]
        second_items = [
            {
                "note_id": "n2",
                "title": "B2",
                "author": "u2",
                "note_type": "image",
                "cover_url": "",
                "note_url": "url2",
                "xsec_token": "x2",
                "liked_count": 3,
            }
        ]

        async with get_db_context() as db:
            removed_first = await _sync_collection_snapshot(
                db,
                session_id=self.session_id,
                user_id=self.user_id,
                source_type="favorites",
                items=first_items,
            )
        async with get_db_context() as db:
            removed_second = await _sync_collection_snapshot(
                db,
                session_id=self.session_id,
                user_id=self.user_id,
                source_type="favorites",
                items=second_items,
            )

        self.assertEqual(removed_first, 0)
        self.assertEqual(removed_second, 1)

        async with get_db_context() as db:
            collection = (
                await db.execute(select(SourceCollection).where(SourceCollection.session_id == self.session_id))
            ).scalar_one()
            records = (
                await db.execute(
                    select(CollectionItemRecord)
                    .where(CollectionItemRecord.collection_id == collection.id)
                    .order_by(CollectionItemRecord.note_id)
                )
            ).scalars().all()

        self.assertEqual(collection.item_count, 1)
        self.assertEqual(len(records), 2)
        self.assertFalse(records[0].is_active)
        self.assertTrue(records[0].removed_at is not None)
        self.assertTrue(records[1].is_active)
        self.assertEqual(records[1].title, "B2")

    async def test_retry_candidates_only_return_active_memberships(self) -> None:
        items = [
            {
                "note_id": "n1",
                "title": "A",
                "author": "u1",
                "note_type": "image",
                "cover_url": "",
                "note_url": "url1",
                "xsec_token": "x1",
                "liked_count": 1,
            }
        ]

        async with get_db_context() as db:
            await _sync_collection_snapshot(
                db,
                session_id=self.session_id,
                user_id=self.user_id,
                source_type="favorites",
                items=items,
            )
            retry_active = await _resolve_retry_candidates(
                db,
                session_id=self.session_id,
                note_ids=["n1"],
            )

        self.assertEqual(len(retry_active), 1)
        self.assertEqual(retry_active[0]["note_id"], "n1")

        async with get_db_context() as db:
            await _sync_collection_snapshot(
                db,
                session_id=self.session_id,
                user_id=self.user_id,
                source_type="favorites",
                items=[],
            )
            retry_removed = await _resolve_retry_candidates(
                db,
                session_id=self.session_id,
                note_ids=["n1"],
            )

        self.assertEqual(retry_removed, [])

    async def test_sync_api_starts_and_reports_completed_task(self) -> None:
        client = TestClient(app)

        async def fake_sync(task_id: str, *, session_id: str, payload, retry_items=None) -> None:
            async with get_db_context() as db:
                record = (
                    await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
                ).scalar_one()
                record.status = "completed"
                record.progress = 100
                record.current_step = "完成"
                record.message = "mock completed"
                record.added_notes = 2
                record.updated_notes = 1
                record.removed_notes = 1
                record.indexed_notes = 2
                record.total_chunks = 3
                await db.commit()

        with patch("app.routers.knowledge._sync_notes_task", new=fake_sync):
            response = client.post(
                f"/knowledge/sync?session_id={self.session_id}",
                json={
                    "max_items_per_source": 5,
                    "force_refresh": False,
                    "force_reindex": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        status_response = client.get(f"/knowledge/sync/status/{task_id}")
        self.assertEqual(status_response.status_code, 200)
        payload = status_response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["removed_notes"], 1)
        self.assertEqual(payload["indexed_notes"], 2)

    async def test_retry_api_starts_new_task_for_failed_notes(self) -> None:
        client = TestClient(app)
        await _create_sync_task("seed-task", session_id=self.session_id, source_types=["favorites"])
        async with get_db_context() as db:
            record = (
                await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == "seed-task"))
            ).scalar_one()
            record.status = "completed"
            record.progress = 100
            record.current_step = "完成"
            record.failed_notes_json = '["n2"]'
            await db.commit()

        async def fake_sync(task_id: str, *, session_id: str, payload, retry_items=None) -> None:
            async with get_db_context() as db:
                record = (
                    await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
                ).scalar_one()
                record.status = "completed"
                record.progress = 100
                record.current_step = "完成"
                record.message = "retry completed"
                record.processed_notes = len(retry_items or [])
                await db.commit()

        with patch("app.routers.knowledge._resolve_retry_candidates", return_value=[{"note_id": "n2", "source_type": "favorites"}]):
            with patch("app.routers.knowledge._sync_notes_task", new=fake_sync):
                response = client.post(f"/knowledge/sync/retry/seed-task?session_id={self.session_id}")

        self.assertEqual(response.status_code, 200)
        retry_task_id = response.json()["task_id"]
        async with get_db_context() as db:
            retry_task = (
                await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == retry_task_id))
            ).scalar_one_or_none()
        self.assertIsNotNone(retry_task)
        self.assertNotEqual(retry_task_id, "seed-task")

    async def test_index_task_api_starts_and_reports_completed_task(self) -> None:
        client = TestClient(app)

        async def fake_index(task_id: str, *, payload, session_id: str) -> None:
            async with get_db_context() as db:
                record = (
                    await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
                ).scalar_one()
                record.status = "completed"
                record.progress = 100
                record.current_step = "完成"
                record.message = "index completed"
                record.indexed_notes = 3
                record.total_chunks = 7
                await db.commit()

        with patch("app.routers.knowledge._index_notes_task", new=fake_index):
            response = client.post(
                f"/knowledge/index/task?session_id={self.session_id}",
                json={
                    "force_reindex": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        status_response = client.get(f"/knowledge/index/status/{task_id}")
        self.assertEqual(status_response.status_code, 200)
        payload = status_response.json()
        self.assertEqual(payload["task_type"], "index")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["indexed_notes"], 3)

    async def test_index_retry_api_starts_new_task_for_failed_notes(self) -> None:
        client = TestClient(app)
        await _create_sync_task("index-seed-task", session_id=self.session_id, source_types=["favorites"], task_type="index")
        async with get_db_context() as db:
            record = (
                await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == "index-seed-task"))
            ).scalar_one()
            record.status = "completed"
            record.progress = 100
            record.current_step = "完成"
            record.failed_notes_json = '["n5","n7"]'
            await db.commit()

        async def fake_index(task_id: str, *, payload, session_id: str) -> None:
            async with get_db_context() as db:
                record = (
                    await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == task_id))
                ).scalar_one()
                record.status = "completed"
                record.progress = 100
                record.current_step = "完成"
                record.message = "index retry completed"
                record.processed_notes = len(payload.note_ids or [])
                await db.commit()

        with patch("app.routers.knowledge._index_notes_task", new=fake_index):
            response = client.post(f"/knowledge/index/retry/index-seed-task?session_id={self.session_id}")

        self.assertEqual(response.status_code, 200)
        retry_task_id = response.json()["task_id"]
        async with get_db_context() as db:
            retry_task = (
                await db.execute(select(SyncTaskRecord).where(SyncTaskRecord.task_id == retry_task_id))
            ).scalar_one_or_none()
        self.assertIsNotNone(retry_task)
        self.assertEqual(retry_task.task_type, "index")
        self.assertNotEqual(retry_task_id, "index-seed-task")


if __name__ == "__main__":
    unittest.main()
