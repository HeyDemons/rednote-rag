"""
Minimal vector indexing and semantic search service for rednote-rag.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import InvalidDimensionException
from loguru import logger
from openai import OpenAI

from app.config import settings


class RAGService:
    """Manage vector indexing and semantic search for cached notes."""

    def __init__(self, collection_name: str = "rednote_notes"):
        self.collection_name = self._build_collection_name(collection_name)
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.openai_client = None
        if settings.openai_api_key:
            self.openai_client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def split_text(self, text: str) -> list[str]:
        """Chunk text with overlap for retrieval."""
        clean = (text or "").strip()
        if not clean:
            return []

        chunk_size = settings.rag_chunk_size
        overlap = settings.rag_chunk_overlap
        chunks: list[str] = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + chunk_size)
            chunk = clean[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def index_note(self, note: dict[str, Any], *, force_reindex: bool = False) -> int:
        """Index one cached note into Chroma."""
        normalized_content = str(note.get("normalized_content") or "").strip()
        note_id = str(note.get("note_id") or "").strip()
        if not note_id or not normalized_content:
            return 0

        if force_reindex:
            self.delete_note(note_id)

        chunks = self.split_text(normalized_content)
        if not chunks:
            return 0

        embeddings = self.embed_texts(chunks)
        ids = [f"{note_id}:{idx}" for idx in range(len(chunks))]
        metadatas = []
        for idx, _chunk in enumerate(chunks):
            metadatas.append(
                {
                    "note_id": note_id,
                    "title": str(note.get("title") or ""),
                    "author_name": str(note.get("author_name") or ""),
                    "source_type": str(note.get("source_type") or ""),
                    "content_source": str(note.get("content_source") or ""),
                    "note_url": str(note.get("note_url") or ""),
                    "chunk_index": idx,
                }
            )

        try:
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas,
            )
        except InvalidDimensionException:
            self._reset_collection()
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas,
            )
        return len(chunks)

    def delete_note(self, note_id: str) -> None:
        """Delete all indexed chunks for one note."""
        try:
            self.collection.delete(where={"note_id": note_id})
        except Exception as exc:
            logger.warning(f"删除 note 向量失败 [{note_id}]: {exc}")

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        note_ids: list[str] | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run semantic search and return normalized hits."""
        q = (query or "").strip()
        if not q:
            return []

        where: dict[str, Any] | None = None
        clauses: list[dict[str, Any]] = []
        if note_ids:
            clauses.append({"note_id": {"$in": note_ids}})
        if source_type:
            clauses.append({"source_type": source_type})
        if len(clauses) == 1:
            where = clauses[0]
        elif len(clauses) > 1:
            where = {"$and": clauses}

        query_embedding = self.embed_texts([q])[0]
        try:
            result = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where,
            )
        except InvalidDimensionException:
            self._reset_collection()
            return []

        hits: list[dict[str, Any]] = []
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for document, metadata, distance in zip(documents, metadatas, distances):
            score = 1.0 / (1.0 + float(distance))
            hits.append(
                {
                    "note_id": str(metadata.get("note_id", "")),
                    "title": str(metadata.get("title", "")),
                    "author_name": str(metadata.get("author_name", "")),
                    "source_type": str(metadata.get("source_type", "")),
                    "content_source": str(metadata.get("content_source", "")),
                    "note_url": str(metadata.get("note_url", "")),
                    "chunk_index": int(metadata.get("chunk_index", 0)),
                    "score": score,
                    "snippet": str(document),
                }
            )
        return hits

    def get_collection_stats(self) -> dict[str, int]:
        """Return vector collection stats."""
        return {"total_chunks": int(self.collection.count())}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using configured remote API, optionally falling back locally."""
        if self.openai_client:
            try:
                response = self.openai_client.embeddings.create(
                    model=settings.embedding_model,
                    input=texts,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:
                if not settings.allow_local_embed_fallback:
                    raise RuntimeError(
                        "远程 embedding 调用失败，请检查 OPENAI_API_KEY、OPENAI_BASE_URL、EMBEDDING_MODEL 是否正确"
                    ) from exc
                logger.warning(f"远程 embedding 失败，已降级到本地 embedding: {exc}")

        if not settings.allow_local_embed_fallback:
            raise RuntimeError(
                "未配置可用的 embedding 服务。请配置 OPENAI_API_KEY、OPENAI_BASE_URL、EMBEDDING_MODEL，"
                "或显式开启 ALLOW_LOCAL_EMBED_FALLBACK=true"
            )

        return [self._local_embed(text) for text in texts]

    def _local_embed(self, text: str) -> list[float]:
        """Deterministic local fallback embedding for development."""
        dim = settings.embedding_dimension
        vec = [0.0] * dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in re.split(r"[\s,.;:!?()\[\]{}，。！？；：]+", text.lower()) if token]

    @staticmethod
    def _build_collection_name(base_name: str) -> str:
        model_key = re.sub(r"[^a-zA-Z0-9]+", "_", settings.embedding_model).strip("_").lower() or "default"
        return f"{base_name}_{model_key}"

    def _reset_collection(self) -> None:
        """Re-open the model-specific collection."""
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
