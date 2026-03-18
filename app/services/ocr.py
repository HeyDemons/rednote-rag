"""
Image OCR service for Xiaohongshu notes.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Any

import httpx
from openai import OpenAI

from app.config import settings


class OCRService:
    """Extract visible text from note images using a vision-capable OpenAI-compatible model."""

    PROMPT = (
        "你是一个严格的 OCR 引擎。"
        "只提取图片中肉眼可见的文字，不要总结，不要解释，不要改写。"
        "保留原语言和原有换行；如果图片里没有可读文字，返回空字符串。"
    )

    def __init__(self) -> None:
        self.client = None
        if settings.openai_api_key and settings.ocr_model:
            self.client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )

    def extract_note_ocr(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Run OCR for image notes and return normalized OCR fields."""
        try:
            note_type = str(detail.get("note_type") or "image").strip().lower()
            images = [str(url).strip() for url in (detail.get("images") or []) if str(url).strip()]

            if note_type == "video":
                return {
                    "ocr_text": "",
                    "ocr_status": "skipped_video",
                    "ocr_image_count": 0,
                }
            if not images:
                return {
                    "ocr_text": "",
                    "ocr_status": "no_images",
                    "ocr_image_count": 0,
                }
            if not settings.ocr_enabled:
                return {
                    "ocr_text": "",
                    "ocr_status": "disabled",
                    "ocr_image_count": 0,
                }
            if self.client is None:
                return {
                    "ocr_text": "",
                    "ocr_status": "unconfigured",
                    "ocr_image_count": 0,
                }

            processed = 0
            extracted_texts: list[str] = []

            for image_url in images[: settings.ocr_max_images_per_note]:
                try:
                    image_bytes, mime_type = self._download_image(image_url)
                    if not image_bytes:
                        continue

                    text = self._extract_image_text(image_bytes, mime_type)
                    processed += 1
                    if text:
                        extracted_texts.append(text)
                except Exception:
                    continue

            merged_text = self._merge_texts(extracted_texts)
            return {
                "ocr_text": merged_text,
                "ocr_status": "completed" if processed > 0 else "empty",
                "ocr_image_count": processed,
            }
        except Exception:
            return {
                "ocr_text": "",
                "ocr_status": "failed",
                "ocr_image_count": 0,
            }

    def _download_image(self, image_url: str) -> tuple[bytes, str]:
        with httpx.Client(timeout=settings.ocr_timeout_seconds, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
            mime_type = response.headers.get("content-type", "").split(";")[0].strip() or self._guess_mime(image_url)
            return response.content, mime_type

    def _extract_image_text(self, image_bytes: bytes, mime_type: str) -> str:
        payload = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{mime_type};base64,{payload}"

        response = self.client.chat.completions.create(
            model=settings.ocr_model,
            temperature=0,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": self.PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请逐字提取这张图片中的可见文字。"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
        )
        return str(response.choices[0].message.content or "").strip()

    @staticmethod
    def _guess_mime(image_url: str) -> str:
        guessed, _ = mimetypes.guess_type(image_url)
        return guessed or "image/jpeg"

    @staticmethod
    def _merge_texts(texts: list[str]) -> str:
        seen: set[str] = set()
        merged: list[str] = []
        for text in texts:
            clean = str(text).strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            merged.append(clean)
        return "\n\n".join(merged)
