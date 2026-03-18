import unittest

from app.services.content_fetcher import ContentFetcher


class ContentFetcherTestCase(unittest.TestCase):
    def test_build_note_content_merges_cleaned_ocr_text(self) -> None:
        fetcher = ContentFetcher()
        detail = {
            "title": "Nano banana PNG转PPT最终无脑版",
            "content": "正文里已经提到 Adobe Acrobat。",
            "author_name": "科研杀马特",
            "note_type": "image",
            "tags": ["Nanobanana", "gpt"],
            "images": ["img1", "img2"],
            "ocr_text": "\n".join(
                [
                    "Adobe Acrobat",
                    "Adobe Photoshop",
                    "Adobe Photoshop",
                    "立即回答",
                    "发送",
                    "Strategy axes",
                ]
            ),
            "note_url": "https://example.com/note",
            "liked_count": 10,
            "collected_count": 5,
            "comment_count": 1,
            "share_count": 0,
            "source_type": "favorites",
            "published_at": "2026-03-18T10:00:00",
        }

        result = fetcher.build_note_content(detail)

        self.assertEqual(result["content_source"], "merged")
        self.assertIn("图片识别文本：Adobe Photoshop", result["normalized_content"])
        self.assertIn("Strategy axes", result["normalized_content"])
        self.assertNotIn("立即回答", result["normalized_content"])
        self.assertNotIn("发送", result["normalized_content"])

    def test_clean_ocr_text_deduplicates_noise_and_references(self) -> None:
        cleaned = ContentFetcher._clean_ocr_text(
            "\n".join(
                [
                    "测试标题",
                    "作者A",
                    "继续",
                    "继续",
                    "关键流程图",
                    "关键流程图",
                    "超长描述",
                ]
            ),
            title="测试标题",
            raw_content="正文没有这句",
            tags=["标签A"],
            author_name="作者A",
        )

        self.assertNotIn("测试标题", cleaned)
        self.assertNotIn("作者A", cleaned)
        self.assertNotIn("继续", cleaned)
        self.assertEqual(cleaned.count("关键流程图"), 1)
        self.assertIn("超长描述", cleaned)


if __name__ == "__main__":
    unittest.main()
