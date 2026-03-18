"""
Normalize cached note detail into a stable text block for downstream indexing.
"""

from __future__ import annotations

import re
from typing import Any


class ContentFetcher:
    """Build index-ready text from Xiaohongshu note detail."""

    MIN_CONTENT_LENGTH = 30
    MAX_OCR_CHARS = 2000
    OCR_NOISE_TERMS = {
        "立即回答",
        "有问题，尽管问",
        "思考中",
        "正在编写代码",
        "立即生成",
        "发送",
        "重新生成",
        "继续",
        "复制",
        "下载",
        "分享",
    }

    def build_note_content(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Convert normalized note detail fields into a single structured text document."""
        title = str(detail.get("title") or "").strip()
        raw_content = str(detail.get("content") or "").strip()
        author_name = str(detail.get("author_name") or "").strip()
        note_type = str(detail.get("note_type") or "image").strip()
        tags = detail.get("tags") or []
        images = detail.get("images") or []
        ocr_text = self._clean_ocr_text(
            str(detail.get("ocr_text") or "").strip(),
            title=title,
            raw_content=raw_content,
            tags=tags,
            author_name=author_name,
        )
        note_url = str(detail.get("note_url") or "").strip()
        liked_count = int(detail.get("liked_count") or 0)
        collected_count = int(detail.get("collected_count") or 0)
        comment_count = int(detail.get("comment_count") or 0)
        share_count = int(detail.get("share_count") or 0)
        source_type = str(detail.get("source_type") or "").strip()
        published_at = detail.get("published_at")

        parts: list[str] = []

        if title:
            parts.append(f"标题：{title}")
        if raw_content:
            parts.append(f"正文：{raw_content}")
        if tags:
            tag_text = "、".join(str(tag).strip() for tag in tags if str(tag).strip())
            if tag_text:
                parts.append(f"标签：{tag_text}")
        if author_name:
            parts.append(f"作者：{author_name}")
        if ocr_text:
            parts.append(f"图片识别文本：{ocr_text}")

        meta_lines: list[str] = []
        if note_type:
            meta_lines.append(f"类型={note_type}")
        if source_type:
            meta_lines.append(f"来源={source_type}")
        if published_at:
            meta_lines.append(f"发布时间={published_at.isoformat() if hasattr(published_at, 'isoformat') else published_at}")
        if liked_count or collected_count or comment_count or share_count:
            meta_lines.append(
                f"互动=点赞{liked_count} 收藏{collected_count} 评论{comment_count} 分享{share_count}"
            )
        if images:
            meta_lines.append(f"图片数={len(images)}")
        if note_url:
            meta_lines.append(f"链接={note_url}")
        if meta_lines:
            parts.append("元信息：" + "；".join(meta_lines))

        normalized_content = "\n\n".join(part for part in parts if part).strip()

        return {
            "content_source": "merged" if ocr_text else "note_detail",
            "normalized_content": normalized_content,
            "content_length": len(normalized_content),
            "sufficient_for_indexing": len(normalized_content) >= self.MIN_CONTENT_LENGTH,
        }

    @classmethod
    def _clean_ocr_text(
        cls,
        ocr_text: str,
        *,
        title: str,
        raw_content: str,
        tags: list[Any],
        author_name: str,
    ) -> str:
        """Reduce OCR noise before merging it into indexable text."""
        text = re.sub(r"\r\n?", "\n", ocr_text or "").strip()
        if not text:
            return ""

        reference_parts = [title, raw_content, author_name]
        reference_parts.extend(str(tag).strip() for tag in tags if str(tag).strip())
        reference_text = "\n".join(part.lower() for part in reference_parts if part).strip()

        cleaned_lines: list[str] = []
        seen_normalized: set[str] = set()
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip(" \t|")
            if not line:
                continue

            normalized = line.lower()
            if normalized in seen_normalized:
                continue
            if normalized in cls.OCR_NOISE_TERMS:
                continue
            if len(line) <= 1:
                continue
            if reference_text and normalized in reference_text:
                continue

            seen_normalized.add(normalized)
            cleaned_lines.append(line)

        deduped_lines: list[str] = []
        for line in cleaned_lines:
            normalized = line.lower()
            if any(normalized in kept.lower() for kept in deduped_lines if len(normalized) >= 12):
                continue
            deduped_lines.append(line)

        merged = "\n".join(deduped_lines).strip()
        if len(merged) > cls.MAX_OCR_CHARS:
            merged = merged[: cls.MAX_OCR_CHARS].rstrip()
        return merged
