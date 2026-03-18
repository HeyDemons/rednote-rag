"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CollectionItem,
  CollectionSummary,
  collectionsApi,
  knowledgeApi,
  KnowledgeStatusResponse,
  SyncTaskStatusResponse,
} from "@/lib/api";

export interface SelectedNote {
  noteId: string;
  title: string;
  sourceType: string;
  noteUrl?: string;
  xsecToken?: string;
}

interface Props {
  sessionId: string;
  selectedNoteId?: string;
  onNoteSelect: (note: SelectedNote) => void;
  onKnowledgeChanged?: () => void;
}

const SOURCE_LABELS: Record<string, string> = {
  favorites: "我的收藏",
  likes: "我的点赞",
};

export default function SourcesPanel({ sessionId, selectedNoteId, onNoteSelect, onKnowledgeChanged }: Props) {
  const [sourceType, setSourceType] = useState<"favorites" | "likes">("favorites");
  const [summaries, setSummaries] = useState<CollectionSummary[]>([]);
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncState, setSyncState] = useState<SyncTaskStatusResponse | null>(null);
  const [message, setMessage] = useState("");

  const currentSummary = useMemo(
    () => summaries.find((summary) => summary.source_type === sourceType),
    [sourceType, summaries],
  );

  const refreshKnowledge = async () => {
    const data = await knowledgeApi.getStatus(sessionId);
    setKnowledge(data);
  };

  const loadCollections = async () => {
    setLoading(true);
    setMessage("");
    try {
      const [summaryList, page] = await Promise.all([
        collectionsApi.list(sessionId),
        collectionsApi.getItems(sourceType, sessionId),
      ]);
      setSummaries(summaryList);
      setItems(page.items);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "列表加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCollections().catch(() => undefined);
  }, [sessionId, sourceType]);

  useEffect(() => {
    refreshKnowledge().catch(() => undefined);
  }, [sessionId]);

  const pollSync = async (taskId: string) => {
    const result = await knowledgeApi.getSyncStatus(taskId);
    setSyncState(result);
    if (result.status === "completed" || result.status === "failed") {
      setSyncing(false);
      await Promise.all([refreshKnowledge(), loadCollections()]);
      onKnowledgeChanged?.();
      return;
    }
    window.setTimeout(() => {
      pollSync(taskId).catch(() => undefined);
    }, 1800);
  };

  const startSync = async (scope: "all" | "current") => {
    setSyncing(true);
    setMessage("");
    try {
      const payload =
        scope === "current"
          ? { source_type: sourceType, max_items_per_source: 20, force_refresh: false, force_reindex: false }
          : { max_items_per_source: 20, force_refresh: false, force_reindex: false };
      const result = await knowledgeApi.startSync(sessionId, payload);
      await pollSync(result.task_id);
    } catch (err) {
      setSyncing(false);
      setMessage(err instanceof Error ? err.message : "同步失败");
    }
  };

  const startFullSync = async () => {
    setSyncing(true);
    setMessage("");
    try {
      const result = await knowledgeApi.startSync(sessionId, {
        max_items_per_source: 0,
        force_refresh: true,
        force_reindex: false,
      });
      await pollSync(result.task_id);
    } catch (err) {
      setSyncing(false);
      setMessage(err instanceof Error ? err.message : "全量同步失败");
    }
  };

  return (
    <div className="panel-inner">
      <div className="panel-header">
        <div>
          <div className="panel-title">来源面板</div>
        </div>
        <button className="btn btn-ghost" onClick={() => loadCollections().catch(() => undefined)} disabled={loading}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </div>

      <div className="status-grid">
        <div className="status-card">
          <span className="status-label">缓存</span>
          <strong>{knowledge?.cached_notes ?? "--"}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">已索引</span>
          <strong>{knowledge?.indexed_notes ?? "--"}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">Chunks</span>
          <strong>{knowledge?.total_indexed_chunks ?? "--"}</strong>
        </div>
      </div>

      <div className="sync-box">
        <div className="sync-actions">
          <button className="btn btn-primary" onClick={startFullSync} disabled={syncing}>
            {syncing ? "同步中..." : "全量同步"}
          </button>
          <button className="btn btn-outline" onClick={() => startSync("all")} disabled={syncing}>
            增量同步
          </button>
          <button className="btn btn-outline" onClick={() => startSync("current")} disabled={syncing}>
            当前标签
          </button>
        </div>
        {syncState ? (
          <div className="sync-meta">
            <div>{syncState.current_step || syncState.status}</div>
            <div>
              已处理 {syncState.processed_notes}/{syncState.total_candidate_notes} · 新增 {syncState.added_notes} · 索引{" "}
              {syncState.indexed_notes}
            </div>
            <div>全量同步默认跳过 OCR，后续单条缓存或增量同步会补 OCR。</div>
          </div>
        ) : null}
      </div>

      <div className="sources-switch-wrap">
        <div className="segmented segmented-tight">
          {(["favorites", "likes"] as const).map((key) => (
            <button
              key={key}
              className={`segmented-item ${sourceType === key ? "active" : ""}`}
              onClick={() => setSourceType(key)}
            >
              {SOURCE_LABELS[key]}
              {summaries.find((summary) => summary.source_type === key)?.item_count != null ? (
                <span className="segmented-count">
                  {summaries.find((summary) => summary.source_type === key)?.item_count}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <div className="list-meta">
        <span>{currentSummary?.title || SOURCE_LABELS[sourceType]}</span>
        <span>{items.length} 条已加载</span>
      </div>

      <div className="source-list">
        {items.map((item) => (
          <button
            key={item.note_id}
            className={`source-row ${selectedNoteId === item.note_id ? "selected" : ""}`}
            onClick={() =>
              onNoteSelect({
                noteId: item.note_id,
                title: item.title,
                sourceType,
                noteUrl: item.note_url,
                xsecToken: item.xsec_token,
              })
            }
          >
            <div className="source-row-main">
              <div className="source-row-title">{item.title || "Untitled"}</div>
              <div className="source-row-meta">
                <span>{item.author || "匿名作者"}</span>
                <span>{item.note_type}</span>
                <span>{item.liked_count || 0} 赞</span>
              </div>
            </div>
            <span className="status-pill">{sourceType}</span>
          </button>
        ))}
        {!loading && items.length === 0 ? <div className="empty-list">当前列表为空</div> : null}
      </div>

      {message ? <div className="error-banner">{message}</div> : null}
    </div>
  );
}
