"""
Small service wrapper around the vendored xiaohongshu-cli client.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings


VENDORED_XHS_PATH = Path(__file__).resolve().parents[2] / "provider" / "xiaohongshu-cli"
if str(VENDORED_XHS_PATH) not in sys.path:
    sys.path.insert(0, str(VENDORED_XHS_PATH))

from xhs_cli.client import XhsClient  # type: ignore  # noqa: E402
from xhs_cli.command_normalizers import normalize_xhs_user_payload  # type: ignore  # noqa: E402
from xhs_cli.cookies import get_cookies, load_saved_cookies  # type: ignore  # noqa: E402
from xhs_cli.cookies import save_cookies  # type: ignore  # noqa: E402
from xhs_cli.qr_login import (  # type: ignore  # noqa: E402
    _apply_session_cookies,
    _build_saved_cookies,
    _complete_confirmed_session,
)


class XhsCliService:
    """Single integration point for the local xiaohongshu-cli provider."""

    def __init__(self, request_delay: float | None = None):
        self.request_delay = settings.xhs_request_delay if request_delay is None else request_delay

    def login_with_browser_cookies(
        self,
        cookie_source: str = "auto",
        *,
        force_refresh: bool = True,
    ) -> dict[str, Any]:
        """Extract browser cookies, verify them, and return normalized user/session data."""
        source, cookies = get_cookies(cookie_source, force_refresh=force_refresh)
        user = self.get_current_user(cookies)
        return {
            "cookie_source": source,
            "cookies": cookies,
            "user": user,
        }

    def get_current_user(self, cookies: dict[str, str]) -> dict[str, Any]:
        """Verify a cookie jar and normalize the returned profile payload."""
        with XhsClient(cookies, request_delay=self.request_delay) as client:
            info = client.get_self_info()

        user = normalize_xhs_user_payload(info)
        basic = info.get("basic_info", info) if isinstance(info, dict) else {}
        if not isinstance(basic, dict):
            basic = {}

        return {
            "user_id": str(user.get("id", "")),
            "username": str(user.get("username", "")),
            "nickname": str(user.get("nickname", "Unknown")),
            "avatar": str(basic.get("images") or basic.get("image") or basic.get("avatar", "")),
            "ip_location": str(user.get("ip_location", "")),
            "desc": str(user.get("desc", "")),
            "guest": bool(user.get("guest", False)),
            "raw": info,
        }

    def get_saved_login_status(self) -> dict[str, Any]:
        """Inspect current saved cookies, if any."""
        cookies = load_saved_cookies()
        if not cookies:
            return {"authenticated": False, "reason": "no_saved_cookies"}

        saved_at = cookies.pop("saved_at", None)
        user = self.get_current_user(cookies)
        return {
            "authenticated": not user["guest"] and bool(user["nickname"]) and user["nickname"] != "Unknown",
            "saved_at": saved_at,
            "cookies": cookies,
            "user": user,
        }

    def start_qrcode_login(self) -> dict[str, Any]:
        """Create a QR login session and return the QR URL plus temporary cookies."""
        a1 = self._generate_cookie_token(52)
        webid = self._generate_cookie_token(32)
        tmp_cookies = {"a1": a1, "webId": webid}

        with XhsClient(tmp_cookies, request_delay=0) as client:
            try:
                activate_data = client.login_activate()
                _apply_session_cookies(client, activate_data)
            except Exception:
                pass

            qr_data = client.create_qr_login()

            return {
                "cookies": dict(client.cookies),
                "qr_id": str(qr_data["qr_id"]),
                "code": str(qr_data["code"]),
                "qr_url": str(qr_data["url"]),
            }

    def poll_qrcode_status(
        self,
        *,
        cookies: dict[str, str],
        qr_id: str,
        code: str,
    ) -> dict[str, Any]:
        """Poll current QR login status."""
        with XhsClient(cookies, request_delay=0) as client:
            status_data = client.check_qr_status(qr_id, code)

        code_status = int(status_data.get("codeStatus", -1))
        status = "waiting"
        if code_status == 1:
            status = "scanned"
        elif code_status == 2:
            status = "confirmed"

        return {
            "status": status,
            "code_status": code_status,
            "confirmed_user_id": str(status_data.get("userId", "")).strip(),
            "raw": status_data,
        }

    def complete_qrcode_login(
        self,
        *,
        cookies: dict[str, str],
        qr_id: str,
        code: str,
        confirmed_user_id: str = "",
    ) -> dict[str, Any]:
        """Finalize QR login, persist cookies, and return normalized user info."""
        base_cookies = dict(cookies)
        with XhsClient(base_cookies, request_delay=0) as client:
            if confirmed_user_id:
                _complete_confirmed_session(
                    client,
                    qr_id,
                    code,
                    confirmed_user_id,
                )
            else:
                completion_data = client.complete_qr_login(qr_id, code)
                _apply_session_cookies(client, completion_data)

            finalized = _build_saved_cookies(
                str(base_cookies.get("a1", "")),
                str(base_cookies.get("webId", "")),
                client.cookies,
            )
            save_cookies(finalized)

        user = self.get_current_user(finalized)
        return {
            "cookies": finalized,
            "user": user,
        }

    def list_liked_notes(self, cookies: dict[str, str], user_id: str, cursor: str = "") -> dict[str, Any]:
        """List liked notes for a user."""
        with XhsClient(cookies, request_delay=self.request_delay) as client:
            data = client.get_user_likes(user_id, cursor=cursor)
        return self._normalize_paged_notes(data, source_type="likes")

    def list_favorited_notes(self, cookies: dict[str, str], user_id: str, cursor: str = "") -> dict[str, Any]:
        """List favorited notes for a user."""
        with XhsClient(cookies, request_delay=self.request_delay) as client:
            data = client.get_user_favorites(user_id, cursor=cursor)
        return self._normalize_paged_notes(data, source_type="favorites")

    def list_notes_by_source(
        self,
        source_type: str,
        cookies: dict[str, str],
        user_id: str,
        cursor: str = "",
    ) -> dict[str, Any]:
        """Dispatch note listing by logical source type."""
        if source_type == "likes":
            return self.list_liked_notes(cookies, user_id, cursor=cursor)
        if source_type == "favorites":
            return self.list_favorited_notes(cookies, user_id, cursor=cursor)
        raise ValueError(f"unsupported source_type: {source_type}")

    def fetch_note_detail(
        self,
        *,
        cookies: dict[str, str],
        note_id: str,
        xsec_token: str = "",
        source_type: str = "",
        note_url: str = "",
    ) -> dict[str, Any]:
        """Fetch and normalize one note detail."""
        xsec_source = f"pc_{source_type}" if source_type else ""

        with XhsClient(cookies, request_delay=self.request_delay) as client:
            if note_url:
                data = client.get_note_detail(note_id, xsec_token=xsec_token, xsec_source=xsec_source)
            else:
                data = client.get_note_detail(note_id, xsec_token=xsec_token, xsec_source=xsec_source)

        return self._normalize_note_detail_payload(
            data,
            note_id=note_id,
            xsec_token=xsec_token,
            source_type=source_type,
        )

    @staticmethod
    def serialize_cookies(cookies: dict[str, str]) -> str:
        """Persist cookie payload as JSON."""
        return json.dumps(cookies, ensure_ascii=False)

    @staticmethod
    def deserialize_cookies(cookie_json: str) -> dict[str, str]:
        """Load cookie payload from JSON string."""
        data = json.loads(cookie_json)
        if not isinstance(data, dict):
            raise ValueError("cookie_json must decode to an object")
        return {str(k): str(v) for k, v in data.items()}

    @staticmethod
    def _normalize_paged_notes(data: dict[str, Any], *, source_type: str) -> dict[str, Any]:
        """Normalize xiaohongshu paged note responses into API-friendly payloads."""
        notes = data.get("notes", [])
        items = [item for item in (XhsCliService._normalize_note_summary(note, source_type=source_type) for note in notes) if item]
        return {
            "items": items,
            "has_more": bool(data.get("has_more", False)),
            "cursor": str(data.get("cursor", "")),
            "count": len(items),
        }

    @staticmethod
    def parse_count(value: Any) -> int:
        """Best-effort parse of Xiaohongshu count strings like 928, 4.2万, 10万+."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if value is None:
            return 0

        text = str(value).strip()
        if not text:
            return 0

        text = text.replace(",", "").replace("+", "")
        try:
            return int(text)
        except ValueError:
            pass

        if text.endswith("万"):
            base = text[:-1].strip()
            try:
                return int(float(base) * 10000)
            except ValueError:
                return 0

        if text.endswith("千"):
            base = text[:-1].strip()
            try:
                return int(float(base) * 1000)
            except ValueError:
                return 0

        return 0

    @staticmethod
    def _generate_cookie_token(length: int) -> str:
        import random

        return "".join(random.choices("0123456789abcdef", k=length))

    @staticmethod
    def _normalize_note_summary(note: dict[str, Any], *, source_type: str) -> dict[str, Any] | None:
        """Extract stable list fields from likes/favorites note payloads."""
        if not isinstance(note, dict):
            return None

        interact = note.get("interact_info", {}) or {}
        cover = note.get("cover") or {}
        user = note.get("user", {}) or {}
        note_id = str(note.get("note_id", note.get("id", ""))).strip()
        xsec_token = str(note.get("xsec_token", "")).strip()
        if not note_id:
            return None

        cover_url = ""
        if isinstance(cover, dict):
            cover_url = str(
                cover.get("url_default")
                or cover.get("url_pre")
                or cover.get("url")
                or ""
            )
        elif isinstance(cover, str):
            cover_url = cover

        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            note_url = f"{note_url}?xsec_token={xsec_token}&xsec_source=pc_{source_type}"

        liked_count = XhsCliService.parse_count(interact.get("liked_count", note.get("liked_count", 0)))

        return {
            "note_id": note_id,
            "title": str(note.get("title") or note.get("display_title") or "").strip() or "Untitled",
            "author": str(user.get("nickname", "")),
            "source_type": source_type,
            "note_type": "video" if note.get("type") == "video" else "image",
            "liked_count": liked_count,
            "cover_url": cover_url,
            "note_url": note_url,
            "xsec_token": xsec_token,
            "published_at": note.get("time"),
        }

    @classmethod
    def _normalize_note_detail_payload(
        cls,
        data: dict[str, Any],
        *,
        note_id: str,
        xsec_token: str = "",
        source_type: str = "",
    ) -> dict[str, Any]:
        """Normalize detail payload from feed/html response into a stable schema."""
        note = cls._extract_note_card(data)
        if not note:
            raise ValueError(f"note detail payload is empty for {note_id}")

        user = note.get("user", {}) or {}
        interact = note.get("interact_info", {}) or {}
        images = note.get("image_list", []) or []
        tags = note.get("tag_list", []) or []
        title = str(note.get("title") or note.get("display_title") or "").strip() or "Untitled"
        content = str(note.get("desc") or "").strip()
        real_note_id = str(note.get("note_id") or note_id).strip()
        real_xsec_token = str(xsec_token or note.get("xsec_token") or "").strip()
        note_url = f"https://www.xiaohongshu.com/explore/{real_note_id}"
        if real_xsec_token:
            suffix = f"?xsec_token={real_xsec_token}"
            if source_type:
                suffix += f"&xsec_source=pc_{source_type}"
            note_url += suffix

        published_at = None
        raw_time = note.get("time")
        if raw_time:
            try:
                published_at = datetime.utcfromtimestamp(int(raw_time) / 1000)
            except Exception:
                published_at = None

        normalized_images = []
        for image in images:
            if not isinstance(image, dict):
                continue
            normalized_images.append(
                str(image.get("url_default") or image.get("url_pre") or image.get("url") or "").strip()
            )

        normalized_tags = []
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            name = str(tag.get("name") or "").strip()
            if name:
                normalized_tags.append(name)

        return {
            "note_id": real_note_id,
            "title": title,
            "content": content,
            "note_type": "video" if note.get("type") == "video" else "image",
            "author_id": str(user.get("user_id", "")),
            "author_name": str(user.get("nickname", "")),
            "author_avatar": str(user.get("avatar", "")),
            "liked_count": cls.parse_count(interact.get("liked_count", 0)),
            "collected_count": cls.parse_count(interact.get("collected_count", 0)),
            "comment_count": cls.parse_count(interact.get("comment_count", 0)),
            "share_count": cls.parse_count(interact.get("share_count", 0)),
            "image_count": len(normalized_images),
            "tags": normalized_tags,
            "images": [url for url in normalized_images if url],
            "note_url": note_url,
            "xsec_token": real_xsec_token,
            "source_type": source_type,
            "published_at": published_at,
            "raw": data,
        }

    @staticmethod
    def _extract_note_card(data: dict[str, Any]) -> dict[str, Any]:
        """Extract note_card from feed payload or note dict from HTML fallback payload."""
        if not isinstance(data, dict):
            return {}

        items = data.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                note_card = first.get("note_card")
                if isinstance(note_card, dict):
                    return note_card

        if "note_id" in data and ("title" in data or "display_title" in data):
            return data

        return {}
