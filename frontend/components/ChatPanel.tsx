"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatApi, ChatSearchHit, ChatSource, ChatStreamEvent } from "@/lib/api";
import type { SelectedNote } from "@/components/SourcesPanel";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: string;
  sources?: ChatSource[];
}

interface Props {
  sessionId: string;
  selectedNote: SelectedNote | null;
  onNoteSelect: (note: SelectedNote) => void;
}

function compactSnippet(text: string, max = 84) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) {
    return "";
  }
  if (clean.length <= max) {
    return clean;
  }
  return `${clean.slice(0, max).trim()}...`;
}

export default function ChatPanel({ sessionId, selectedNote, onNoteSelect }: Props) {
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchHits, setSearchHits] = useState<ChatSearchHit[]>([]);
  const [lastSources, setLastSources] = useState<ChatSource[]>([]);
  const [pinNote, setPinNote] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
  }, [input]);

  const pinnedNoteIds = useMemo(() => {
    if (!pinNote || !selectedNote?.noteId) {
      return undefined;
    }
    return [selectedNote.noteId];
  }, [pinNote, selectedNote]);

  const sendQuestion = async (question: string) => {
    if (!question.trim()) {
      return;
    }
    const q = question.trim();
    const userId = `${Date.now()}-u`;
    const assistantId = `${Date.now()}-a`;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: q },
      { id: assistantId, role: "assistant", content: "", status: "正在检索并组织答案...", sources: [] },
    ]);
    setLoading(true);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "52px";
    }

    try {
      let streamedSources: ChatSource[] = [];
      let streamedAnswer = "";
      const controller = new AbortController();
      streamAbortRef.current = controller;
      await chatApi.stream(
        sessionId,
        {
          question: q,
          k: 5,
          note_ids: pinnedNoteIds,
        },
        {
          onEvent: (event: ChatStreamEvent) => {
            if (event.type === "status") {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId ? { ...message, status: event.stage || "处理中..." } : message,
                ),
              );
              return;
            }

            if (event.type === "meta") {
              streamedSources = event.sources || [];
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId ? { ...message, sources: streamedSources } : message,
                ),
              );
              setLastSources(streamedSources);
              return;
            }

            if (event.type === "delta") {
              streamedAnswer += event.delta || "";
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId ? { ...message, content: streamedAnswer, status: "正在生成回答" } : message,
                ),
              );
              return;
            }

            if (event.type === "done") {
              const finalAnswer = (event.answer || streamedAnswer || "").trim();
              const finalSources = event.sources || streamedSources;
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId
                    ? { ...message, content: finalAnswer, status: undefined, sources: finalSources }
                    : message,
                ),
              );
              setLastSources(finalSources);
              return;
            }

            if (event.type === "error") {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId
                    ? {
                        ...message,
                        status: undefined,
                        content: `错误：${event.error || "问答失败"}`,
                      }
                    : message,
                ),
              );
            }
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                status: undefined,
                content: `错误：${err instanceof Error ? err.message : "问答失败"}`,
              }
            : message,
        ),
      );
    } finally {
      streamAbortRef.current = null;
      setLoading(false);
    }
  };

  const stopStreaming = () => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setLoading(false);
  };

  const runSearch = async (question: string) => {
    if (!question.trim()) {
      return;
    }
    setSearching(true);
    try {
      const data = await chatApi.search(sessionId, {
        question: question.trim(),
        k: 12,
        note_ids: pinnedNoteIds,
      });
      setSearchHits(data.hits);
      setLastSources(
        data.hits.map((hit) => ({
          note_id: hit.note_id,
          title: hit.title,
          author_name: hit.author_name,
          source_type: hit.source_type,
          content_source: hit.content_source,
          note_url: hit.note_url,
          snippet: hit.snippet,
        })),
      );
    } catch (err) {
      setSearchHits([]);
      setLastSources([]);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="panel-inner">
      <div className="panel-header">
        <div>
          <div className="panel-title">工作台</div>
        </div>
        <div className="panel-actions">
          <button className={`btn ${mode === "ask" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("ask")}>
            问答
          </button>
          <button className={`btn ${mode === "search" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("search")}>
            检索
          </button>
        </div>
      </div>

      <div className="workspace-main">
        <section className="conversation-column">
          {selectedNote ? (
            <div className="conversation-toolbar">
              <div className="panel-actions">
                <span className="status-pill">当前帖子：{selectedNote.title}</span>
                <label className="pin-toggle">
                  <input type="checkbox" checked={pinNote} onChange={(event) => setPinNote(event.target.checked)} />
                  仅针对当前帖子
                </label>
              </div>
            </div>
          ) : null}

          {mode === "ask" ? (
            <>
              <div className="chat-scroll">
                {messages.length === 0 ? (
                  <div className="empty-state">
                    <div className="status-pill">检索就绪</div>
                    <p className="empty-copy">把收藏和点赞转成一个可直接提问的小红书知识库。</p>
                  </div>
                ) : (
                  <div className="chat-window">
                    {messages.map((message) => (
                      <div key={message.id} className={`message ${message.role}`}>
                        <div className="message-bubble">
                          {message.status ? <div className="message-status">{message.status}</div> : null}
                          <ReactMarkdown className="markdown" remarkPlugins={[remarkGfm]}>
                            {message.content || " "}
                          </ReactMarkdown>
                          {message.sources?.length ? (
                            <div className="source-link-list">
                              {message.sources.map((source) => (
                                <button
                                  key={`${message.id}-${source.note_id}`}
                                  className="source-chip"
                                  onClick={() =>
                                    onNoteSelect({
                                      noteId: source.note_id,
                                      title: source.title,
                                      sourceType: source.source_type,
                                      noteUrl: source.note_url,
                                    })
                                  }
                                >
                                  {source.title}
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}
                    <div ref={endRef} />
                  </div>
                )}
              </div>

              <div className="composer">
                <div className="composer-shell">
                  <textarea
                    ref={textareaRef}
                    value={input}
                    rows={1}
                    placeholder={selectedNote ? `围绕《${selectedNote.title}》继续提问` : "输入你的问题"}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        sendQuestion(input).catch(() => undefined);
                      }
                    }}
                  />
                  <button
                    className="composer-send"
                    onClick={() => {
                      if (loading) {
                        stopStreaming();
                        return;
                      }
                      sendQuestion(input).catch(() => undefined);
                    }}
                    disabled={!loading && !input.trim()}
                    aria-label={loading ? "停止生成" : "发送"}
                    title={loading ? "停止生成" : "发送"}
                  >
                    {loading ? "■" : "↑"}
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="search-mode">
              <div className="search-bar">
                <input
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder="输入关键词或问题，先看命中的帖子来源"
                />
                <button className="btn btn-primary" onClick={() => runSearch(searchInput)} disabled={searching || !searchInput.trim()}>
                  {searching ? "搜索中..." : "搜索"}
                </button>
              </div>
              <div className="search-results">
                {searchHits.length === 0 ? (
                  <div className="empty-state compact">
                    <p className="empty-copy">先用检索模式看命中的帖子，再决定要不要继续问答。</p>
                  </div>
                ) : (
                  searchHits.map((hit) => (
                    <button
                      key={hit.note_id}
                      className="search-hit"
                      onClick={() =>
                        onNoteSelect({
                          noteId: hit.note_id,
                          title: hit.title,
                          sourceType: hit.source_type,
                          noteUrl: hit.note_url,
                        })
                      }
                    >
                      <div className="search-hit-top">
                        <strong>{hit.title || "Untitled"}</strong>
                        <span className="status-pill">{hit.source_type || "unknown"}</span>
                      </div>
                      <div className="search-hit-meta">
                        <span>{hit.author_name || "匿名作者"}</span>
                        <span>{hit.chunk_count} chunks</span>
                        <span>{hit.score.toFixed(4)}</span>
                      </div>
                      <p>{hit.snippet}</p>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </section>

        <aside className="context-column">
          <section className="context-card">
            <div className="context-head">
              <div>
                <div className="panel-title small">来源窗口</div>
                <div className="panel-subtitle">展示最近一次问答或检索命中的来源</div>
              </div>
            </div>
            <div className="context-list">
              {lastSources.length === 0 ? (
                <div className="inspector-empty">这里会显示命中的来源卡片。</div>
              ) : (
                lastSources.map((source) => (
                  <div key={`${source.note_id}-${source.title}`} className="context-row">
                    <button
                      className="context-row-link"
                      onClick={() => {
                        if (source.note_url) {
                          window.open(source.note_url, "_blank", "noopener,noreferrer");
                        }
                      }}
                    >
                      <strong>{source.title}</strong>
                      <span>{compactSnippet(source.snippet)}</span>
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
