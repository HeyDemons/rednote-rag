"""
RAG chat endpoints.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from openai import OpenAI

from app.config import settings
from app.error_handling import raise_api_error
from app.models import ChatRequest, ChatResponse, ChatSearchHit, ChatSearchResponse, ChatSource, ChatStreamEvent
from app.routers.auth import get_session
from app.routers.knowledge import get_rag_service


router = APIRouter(prefix="/chat", tags=["chat"])


def _get_llm_client() -> OpenAI:
    if not settings.openai_api_key:
        raise_api_error(400, "未配置 LLM API Key", error_code="LLM_API_KEY_MISSING")
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


def _raise_chat_error(exc: Exception) -> None:
    message = str(exc)
    if "embedding" in message.lower() or "OPENAI_API_KEY" in message or "EMBEDDING_MODEL" in message:
        raise_api_error(400, message, error_code="EMBEDDING_CONFIG_INVALID")
    logger.exception("问答链路失败")
    raise_api_error(500, "问答失败", error_code="CHAT_PIPELINE_FAILED")


def _is_list_question(question: str) -> bool:
    list_terms = ["有哪些", "有什么", "列表", "清单", "目录", "都有哪些", "列出", "罗列", "多少个", "几个"]
    return any(term in question for term in list_terms)


def _is_summary_question(question: str) -> bool:
    summary_terms = ["总结", "概述", "概括", "分析", "梳理", "提炼", "回顾", "复盘", "要点", "重点", "关键点", "核心", "讲了什么", "讲些什么"]
    return any(term in question for term in summary_terms)


def _is_general_question(question: str) -> bool:
    cleaned = re.sub(r"[\W_]+", "", question, flags=re.UNICODE).lower()
    if not cleaned:
        return False

    direct_terms = {
        "你好", "你好呀", "你好啊", "嗨", "嗨呀", "哈喽", "哈喽呀", "hello", "hi",
        "在吗", "你是谁", "你能做什么", "谢谢", "谢谢啦", "谢了", "晚安", "早安", "早上好",
    }
    if cleaned in direct_terms:
        return True

    greeting_prefixes = ("你好", "嗨", "哈喽", "hello", "hi", "在吗", "谢谢")
    filler_suffixes = (
        "呀", "啊", "呀呀", "啊啊", "啦", "呢", "哦", "喔", "哇", "嘛", "呐", "哈", "hhh", "hh",
    )
    if any(cleaned.startswith(prefix) for prefix in greeting_prefixes):
        residual = cleaned
        for prefix in greeting_prefixes:
            if residual.startswith(prefix):
                residual = residual[len(prefix):]
                break
        while residual:
            trimmed = False
            for suffix in filler_suffixes:
                if residual == suffix:
                    residual = ""
                    trimmed = True
                    break
                if residual.endswith(suffix):
                    residual = residual[: -len(suffix)]
                    trimmed = True
                    break
            if not trimmed:
                break
        if residual == "" and len(cleaned) <= 8:
            return True

    return False


def _extract_keywords(question: str) -> list[str]:
    stopwords = {
        "什么", "怎么", "如何", "是否", "可以", "哪个", "哪些", "请问", "一下", "为什么",
        "有没有", "能不能", "能否", "是不是", "是什么", "多少", "哪里", "讲讲", "介绍",
        "总结", "概括", "分析", "解释", "说明", "评价", "区别", "内容", "帖子", "笔记",
        "小红书", "收藏", "点赞", "知识库",
    }
    keywords: list[str] = []
    for kw in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        if kw not in stopwords and kw not in keywords:
            keywords.append(kw)
    for kw in re.findall(r"[A-Za-z0-9]{2,}", question):
        if kw.lower() not in {"hi", "ok"} and kw not in keywords:
            keywords.append(kw)
    return keywords


def _filter_hits_by_keywords(hits: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    keywords = _extract_keywords(question)
    if not keywords:
        return hits

    filtered: list[dict[str, Any]] = []
    for hit in hits:
        title = str(hit.get("title") or "")
        snippet = str(hit.get("snippet") or "")
        if any(kw in title for kw in keywords) or any(kw in snippet for kw in keywords):
            filtered.append(hit)
    if len(filtered) >= min(6, len(hits)):
        return filtered
    return hits


def _expand_retrieval_k(target_notes: int) -> int:
    target = max(int(target_notes or 0), 1)
    return max(target * 6, 24)


def _group_hits_by_note(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for hit in hits:
        note_id = str(hit.get("note_id") or "").strip()
        if not note_id:
            continue

        existing = grouped.get(note_id)
        if not existing:
            grouped[note_id] = {
                "note_id": note_id,
                "title": str(hit.get("title") or ""),
                "author_name": str(hit.get("author_name") or ""),
                "source_type": str(hit.get("source_type") or ""),
                "content_source": str(hit.get("content_source") or ""),
                "note_url": str(hit.get("note_url") or ""),
                "score": float(hit.get("score") or 0.0),
                "snippets": [str(hit.get("snippet") or "").strip()],
                "chunk_indexes": [int(hit.get("chunk_index") or 0)],
            }
            continue

        existing["score"] = max(float(existing.get("score") or 0.0), float(hit.get("score") or 0.0))
        snippet = str(hit.get("snippet") or "").strip()
        if snippet and snippet not in existing["snippets"]:
            existing["snippets"].append(snippet)
        chunk_index = int(hit.get("chunk_index") or 0)
        if chunk_index not in existing["chunk_indexes"]:
            existing["chunk_indexes"].append(chunk_index)

    result = list(grouped.values())
    result.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return result


def _build_note_context(grouped_hits: list[dict[str, Any]], *, include_meta: bool = True) -> str:
    context_blocks = []
    for idx, hit in enumerate(grouped_hits, start=1):
        snippets = [snippet for snippet in hit.get("snippets", []) if snippet]
        merged_snippet = "\n".join(f"- {snippet}" for snippet in snippets[:3])
        lines = [f"[来源 {idx}]", f"标题：{hit.get('title', '')}"]
        if include_meta:
            lines.extend(
                [
                    f"作者：{hit.get('author_name', '')}",
                    f"来源类型：{hit.get('source_type', '')}",
                    f"内容来源：{hit.get('content_source', '')}",
                    f"链接：{hit.get('note_url', '')}",
                ]
            )
        lines.append(f"相关片段：\n{merged_snippet}")
        context_blocks.append(
            "\n".join(lines)
        )
    return "\n\n".join(context_blocks)


def _build_rag_messages(question: str, grouped_hits: list[dict[str, Any]]) -> list[dict]:
    context = _build_note_context(grouped_hits)

    system = (
        "你是一个小红书个人知识库助手。\n"
        "请严格基于提供的检索片段回答问题。\n"
        "要求：\n"
        "1. 优先直接回答用户问题\n"
        "2. 回答要简洁、有条理\n"
        "3. 不要编造检索片段里没有的信息\n"
        "4. 如果信息不足，要明确说“现有检索内容不足以完全回答”\n"
        "5. 如有必要，可在回答中提到来源标题\n\n"
        f"检索内容：\n{context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def _build_list_messages(question: str, grouped_hits: list[dict[str, Any]]) -> list[dict]:
    context = _build_note_context(grouped_hits, include_meta=False)
    system = (
        "你是一个小红书个人知识库助手。\n"
        "用户问的是清单或枚举类问题，请基于检索结果直接列出相关帖子。\n"
        "要求：\n"
        "1. 只列与问题相关的条目\n"
        "2. 优先按主题归类或按重要性排序\n"
        "3. 每条尽量包含标题和一句简短说明\n"
        "4. 不要编造未出现在检索结果中的内容\n\n"
        f"检索内容：\n{context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def _build_summary_messages(question: str, grouped_hits: list[dict[str, Any]]) -> list[dict]:
    context = _build_note_context(grouped_hits)
    system = (
        "你是一个小红书个人知识库助手。\n"
        "用户问的是总结、概括或提炼类问题，请基于检索结果做结构化总结。\n"
        "要求：\n"
        "1. 先给结论，再展开要点\n"
        "2. 只使用检索结果中明确出现的信息\n"
        "3. 如果信息覆盖面不够，要明确指出范围有限\n"
        "4. 必要时可以提到帖子标题作为来源\n\n"
        f"检索内容：\n{context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def _build_direct_messages(question: str) -> list[dict]:
    system = (
        "你是一个小红书个人知识库助手。\n"
        "当前问题不需要检索知识库内容时，请直接自然回答。\n"
        "如果用户在打招呼，可以顺带说明你可以帮助检索、总结和追溯收藏或点赞的小红书帖子。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def _prepare_chat_payload(question: str, hits: list[dict[str, Any]]) -> tuple[list[dict], list[dict[str, Any]]]:
    filtered_hits = _filter_hits_by_keywords(hits, question)
    grouped_hits = _group_hits_by_note(filtered_hits)

    if _is_list_question(question):
        return _build_list_messages(question, grouped_hits), grouped_hits
    if _is_summary_question(question):
        return _build_summary_messages(question, grouped_hits), grouped_hits
    return _build_rag_messages(question, grouped_hits), grouped_hits


def _build_sources(grouped_hits: list[dict[str, Any]], *, limit: int = 3) -> list[ChatSource]:
    sources: list[ChatSource] = []
    for hit in grouped_hits[:limit]:
        snippet = ""
        snippets = [item for item in hit.get("snippets", []) if item]
        if snippets:
            snippet = snippets[0]
        sources.append(
            ChatSource(
                note_id=str(hit.get("note_id") or ""),
                title=str(hit.get("title") or ""),
                author_name=str(hit.get("author_name") or ""),
                source_type=str(hit.get("source_type") or ""),
                content_source=str(hit.get("content_source") or ""),
                note_url=str(hit.get("note_url") or ""),
                snippet=snippet,
            )
        )
    return sources


def _build_search_hits(grouped_hits: list[dict[str, Any]], *, limit: int = 10) -> list[ChatSearchHit]:
    search_hits: list[ChatSearchHit] = []
    for hit in grouped_hits[:limit]:
        snippets = [item for item in hit.get("snippets", []) if item]
        snippet = snippets[0] if snippets else ""
        search_hits.append(
            ChatSearchHit(
                note_id=str(hit.get("note_id") or ""),
                title=str(hit.get("title") or ""),
                author_name=str(hit.get("author_name") or ""),
                source_type=str(hit.get("source_type") or ""),
                content_source=str(hit.get("content_source") or ""),
                note_url=str(hit.get("note_url") or ""),
                score=float(hit.get("score") or 0.0),
                chunk_count=len(hit.get("chunk_indexes", [])),
                snippet=snippet,
            )
        )
    return search_hits


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _create_completion_stream(
    client: OpenAI,
    *,
    messages: list[dict[str, Any]],
) -> Any:
    return client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.2,
        stream=True,
    )


async def _bridge_llm_stream(
    *,
    question: str,
    messages: list[dict[str, Any]],
    sources: list[ChatSource],
    stage_events: list[str],
    error_tag: str,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    for stage in stage_events:
        yield _sse_event("status", ChatStreamEvent(type="status", question=question, stage=stage).model_dump())
    yield _sse_event("meta", ChatStreamEvent(type="meta", question=question, sources=sources).model_dump())

    def producer() -> None:
        client = _get_llm_client()
        answer_parts: list[str] = []
        try:
            stream = _create_completion_stream(client, messages=messages)
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                answer_parts.append(delta)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ("delta", ChatStreamEvent(type="delta", delta=delta).model_dump()),
                )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                (
                    "done",
                    ChatStreamEvent(
                        type="done",
                        question=question,
                        answer="".join(answer_parts).strip(),
                        sources=sources,
                    ).model_dump(),
                ),
            )
        except Exception:
            logger.exception("LLM 流式调用失败 [{}]", error_tag)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("error", ChatStreamEvent(type="error", error="LLM 调用失败", sources=sources).model_dump()),
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=producer, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        event, payload = item
        yield _sse_event(event, payload)


async def _stream_direct_answer(question: str) -> AsyncIterator[str]:
    async for chunk in _bridge_llm_stream(
        question=question,
        messages=_build_direct_messages(question),
        sources=[],
        stage_events=["正在准备回答", "正在生成回答"],
        error_tag="direct",
    ):
        yield chunk


async def _stream_rag_answer(
    question: str,
    *,
    payload: ChatRequest,
) -> AsyncIterator[str]:
    rag = get_rag_service()
    yield _sse_event("status", ChatStreamEvent(type="status", question=question, stage="正在检索相关内容").model_dump())
    try:
        hits = rag.search(
            question,
            k=payload.k,
            note_ids=payload.note_ids,
            source_type=payload.source_type.value if payload.source_type else None,
        )
    except Exception as exc:
        _raise_chat_error(exc)

    if not hits:
        done = ChatStreamEvent(
            type="done",
            question=question,
            answer="当前知识库中没有检索到足够相关的内容，请先完成入库或换一个更具体的问题。",
            sources=[],
        )
        yield _sse_event("done", done.model_dump())
        return

    messages, grouped_hits = _prepare_chat_payload(question, hits)
    sources = _build_sources(grouped_hits)
    async for chunk in _bridge_llm_stream(
        question=question,
        messages=messages,
        sources=sources,
        stage_events=["正在整理来源", "正在生成回答"],
        error_tag="rag",
    ):
        yield chunk


@router.post("/search", response_model=ChatSearchResponse)
async def search_for_chat(
    payload: ChatRequest,
    session_id: str = Query(..., description="会话 ID"),
) -> ChatSearchResponse:
    """Return deduplicated retrieval hits for chat/source preview UIs."""
    question = payload.question.strip()
    if not question:
        raise_api_error(400, "问题不能为空", error_code="QUESTION_EMPTY")

    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    rag = get_rag_service()
    try:
        hits = rag.search(
            question,
            k=_expand_retrieval_k(max(payload.k, 5)),
            note_ids=payload.note_ids,
            source_type=payload.source_type.value if payload.source_type else None,
        )
    except Exception as exc:
        _raise_chat_error(exc)

    grouped_hits = _group_hits_by_note(_filter_hits_by_keywords(hits, question))
    return ChatSearchResponse(
        question=question,
        hits=_build_search_hits(grouped_hits, limit=max(payload.k, 8)),
    )


@router.post("/ask", response_model=ChatResponse)
async def ask_question(
    payload: ChatRequest,
    session_id: str = Query(..., description="会话 ID"),
) -> ChatResponse:
    """Answer a question using retrieved note chunks."""
    question = payload.question.strip()
    if not question:
        raise_api_error(400, "问题不能为空", error_code="QUESTION_EMPTY")

    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    if _is_general_question(question):
        client = _get_llm_client()
        try:
            completion = client.chat.completions.create(
                model=settings.llm_model,
                messages=_build_direct_messages(question),
                temperature=0.2,
            )
            answer = (completion.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.exception("LLM 调用失败 [direct]")
            raise_api_error(500, "LLM 调用失败", error_code="LLM_CALL_FAILED")
        return ChatResponse(question=question, answer=answer, sources=[])

    rag = get_rag_service()
    try:
        hits = rag.search(
            question,
            k=_expand_retrieval_k(payload.k),
            note_ids=payload.note_ids,
            source_type=payload.source_type.value if payload.source_type else None,
        )
    except Exception as exc:
        _raise_chat_error(exc)
    if not hits:
        return ChatResponse(
            question=question,
            answer="当前知识库中没有检索到足够相关的内容，请先完成入库或换一个更具体的问题。",
            sources=[],
        )

    messages, grouped_hits = _prepare_chat_payload(question, hits)
    client = _get_llm_client()
    try:
        completion = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0.2,
        )
        answer = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.exception("LLM 调用失败 [rag]")
        raise_api_error(500, "LLM 调用失败", error_code="LLM_CALL_FAILED")

    return ChatResponse(
        question=question,
        answer=answer,
        sources=_build_sources(grouped_hits),
    )


@router.post("/stream")
async def stream_question(
    payload: ChatRequest,
    session_id: str = Query(..., description="会话 ID"),
) -> StreamingResponse:
    """Stream an answer using SSE."""
    question = payload.question.strip()
    if not question:
        raise_api_error(400, "问题不能为空", error_code="QUESTION_EMPTY")

    session = await get_session(session_id)
    if not session:
        raise_api_error(401, "未登录或会话已失效", error_code="SESSION_INVALID")

    if _is_general_question(question):
        generator = _stream_direct_answer(question)
    else:
        generator = _stream_rag_answer(question, payload=payload)

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
