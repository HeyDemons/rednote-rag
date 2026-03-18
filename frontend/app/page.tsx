"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ChatPanel from "@/components/ChatPanel";
import LoginModal from "@/components/LoginModal";
import SourcesPanel, { SelectedNote } from "@/components/SourcesPanel";
import { authApi, SessionUserInfo } from "@/lib/api";

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [user, setUser] = useState<SessionUserInfo | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [selectedNote, setSelectedNote] = useState<SelectedNote | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [leftWidth, setLeftWidth] = useState(340);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const savedSession = localStorage.getItem("rednote_session");
    const savedUser = localStorage.getItem("rednote_user");
    if (savedSession) {
      setSessionId(savedSession);
    }
    if (savedUser) {
      setUser(JSON.parse(savedUser) as SessionUserInfo);
    }
  }, []);

  const onLogin = (nextSessionId: string, nextUser: SessionUserInfo) => {
    setSessionId(nextSessionId);
    setUser(nextUser);
    setShowLogin(false);
    localStorage.setItem("rednote_session", nextSessionId);
    localStorage.setItem("rednote_user", JSON.stringify(nextUser));
  };

  const onLogout = async () => {
    if (sessionId) {
      await authApi.logout(sessionId).catch(() => undefined);
    }
    setSessionId(null);
    setUser(null);
    setSelectedNote(null);
    localStorage.removeItem("rednote_session");
    localStorage.removeItem("rednote_user");
  };

  const handleMouseDown = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback(
    (event: MouseEvent) => {
      if (!isDragging || !containerRef.current) {
        return;
      }
      const rect = containerRef.current.getBoundingClientRect();
      const width = event.clientX - rect.left;
      const min = 280;
      const max = rect.width * 0.5;
      setLeftWidth(Math.max(min, Math.min(max, width)));
    },
    [isDragging],
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (!isDragging) {
      return;
    }
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [handleMouseMove, handleMouseUp, isDragging]);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M4 6h16M4 12h16M4 18h10" />
            </svg>
          </div>
          <div>
            <span className="brand-title">Rednote Atlas · 个人知识库</span>
            <span className="brand-subtitle">Save • Retrieve • Ask</span>
          </div>
        </div>

        <div className="topbar-actions">
          {user ? (
            <>
              <span className="user-chip">
                <span>已登录</span>
                <strong>{user.nickname}</strong>
              </span>
              <button onClick={onLogout} className="btn btn-ghost">
                退出
              </button>
            </>
          ) : (
            <button onClick={() => setShowLogin(true)} className="btn btn-primary">
              登录并开始
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        {!sessionId ? (
          <section className="hero">
            <div className="hero-content">
              <span className="hero-kicker">让你的小红书收藏和点赞不再吃灰</span>
              <h1 className="hero-title">把“囤帖”变成真正可检索的知识工作台</h1>
              <p className="hero-desc">
                技术帖、保研经验、公开课复盘、实习面经、知识总结，都会被同步到本地缓存、OCR、向量检索和问答工作台里。
              </p>
              <div className="hero-actions">
                <button className="btn btn-primary btn-lg" onClick={() => setShowLogin(true)}>
                  登录并开始构建
                </button>
              </div>
            </div>

            <div className="hero-features">
              <div className="pipeline-row">
                {[
                  { icon: "1", title: "同步", desc: "连接点赞与收藏" },
                  { icon: "2", title: "提取", desc: "正文 + OCR 入库" },
                  { icon: "3", title: "检索", desc: "语义搜索来源" },
                  { icon: "4", title: "问答", desc: "基于来源回答" },
                ].map((item) => (
                  <div key={item.title} className="pipeline-card">
                    <span className="pipeline-icon">{item.icon}</span>
                    <div className="pipeline-text">
                      <strong>{item.title}</strong>
                      <span>{item.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : (
          <section className="workspace" ref={containerRef}>
            <aside className="panel panel-sources" style={{ width: leftWidth, flexShrink: 0 }}>
              <SourcesPanel
                key={`${sessionId}-${refreshKey}`}
                sessionId={sessionId}
                selectedNoteId={selectedNote?.noteId}
                onNoteSelect={setSelectedNote}
                onKnowledgeChanged={() => setRefreshKey((value) => value + 1)}
              />
            </aside>

            <div className="resizer" onMouseDown={handleMouseDown} />

            <section className="panel panel-chat">
              <ChatPanel sessionId={sessionId} selectedNote={selectedNote} onNoteSelect={setSelectedNote} />
            </section>
          </section>
        )}
      </main>

      <footer className="app-footer">
        <p>Rednote Atlas © 2026 · 基于 xiaohongshu-cli + FastAPI + Chroma · 由 AI 驱动</p>
      </footer>

      <LoginModal isOpen={showLogin} onClose={() => setShowLogin(false)} onSuccess={onLogin} />
    </div>
  );
}
