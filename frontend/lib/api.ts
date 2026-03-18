export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (response.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("rednote_session");
    localStorage.removeItem("rednote_user");
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || text || `请求失败: ${response.status}`);
  }

  return data as T;
}

export interface SessionUserInfo {
  user_id: string;
  username: string;
  nickname: string;
  avatar: string;
  ip_location: string;
  desc: string;
}

export interface AuthSessionResponse {
  authenticated: boolean;
  session_id?: string | null;
  user?: SessionUserInfo | null;
  cookie_source?: string | null;
}

export interface QrLoginStartResponse {
  login_id: string;
  qr_url: string;
  expires_in_seconds: number;
  status: string;
}

export interface QrLoginStatusResponse {
  login_id: string;
  status: string;
  authenticated: boolean;
  session_id?: string | null;
  user?: SessionUserInfo | null;
  cookie_source?: string | null;
  expires_in_seconds: number;
  message: string;
}

export interface CollectionSummary {
  source_type: "favorites" | "likes";
  title: string;
  item_count?: number | null;
  is_selected: boolean;
}

export interface CollectionItem {
  note_id: string;
  title: string;
  author: string;
  note_type: string;
  liked_count: number;
  cover_url: string;
  note_url: string;
  xsec_token: string;
  published_at?: number | null;
}

export interface CollectionItemsResponse {
  source_type: string;
  items: CollectionItem[];
  cursor: string;
  has_more: boolean;
  count: number;
}

export interface KnowledgeStatusResponse {
  cached_notes: number;
  indexed_notes: number;
  total_indexed_chunks: number;
  latest_indexed_at?: string | null;
}

export interface SyncStartResponse {
  task_id: string;
  message: string;
}

export interface SyncTaskStatusResponse {
  task_id: string;
  status: string;
  progress: number;
  current_step: string;
  source_types: string[];
  total_remote_notes: number;
  total_candidate_notes: number;
  processed_notes: number;
  added_notes: number;
  updated_notes: number;
  removed_notes: number;
  skipped_notes: number;
  indexed_notes: number;
  total_chunks: number;
  failed_notes: string[];
  message: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ChatSearchHit {
  note_id: string;
  title: string;
  author_name: string;
  source_type: string;
  content_source: string;
  note_url: string;
  score: number;
  chunk_count: number;
  snippet: string;
}

export interface ChatSearchResponse {
  question: string;
  hits: ChatSearchHit[];
}

export interface ChatSource {
  note_id: string;
  title: string;
  author_name: string;
  source_type: string;
  content_source: string;
  note_url: string;
  snippet: string;
}

export interface ChatResponse {
  question: string;
  answer: string;
  sources: ChatSource[];
}

export interface ChatStreamEvent {
  type: "meta" | "status" | "delta" | "done" | "error";
  question?: string | null;
  stage?: string | null;
  delta?: string | null;
  answer?: string | null;
  sources?: ChatSource[];
  error?: string | null;
}

export interface NoteDetail {
  note_id: string;
  title: string;
  content: string;
  normalized_content: string;
  content_source: string;
  note_type: string;
  author_id: string;
  author_name: string;
  author_avatar: string;
  liked_count: number;
  collected_count: number;
  comment_count: number;
  share_count: number;
  image_count: number;
  ocr_text: string;
  ocr_status: string;
  ocr_image_count: number;
  ocr_updated_at?: string | null;
  tags: string[];
  images: string[];
  note_url: string;
  xsec_token: string;
  source_type: string;
  published_at?: string | null;
  last_crawled_at?: string | null;
  process_error: string;
}

export interface CachedNoteResponse {
  cached: boolean;
  note: NoteDetail;
}

export interface ExtractedContentResponse {
  note_id: string;
  title: string;
  content_source: string;
  normalized_content: string;
  content_length: number;
  sufficient_for_indexing: boolean;
}

export interface NoteOcrResponse {
  note_id: string;
  title: string;
  note_type: string;
  ocr_status: string;
  ocr_image_count: number;
  ocr_updated_at?: string | null;
  ocr_text: string;
  ocr_text_length: number;
  cleaned_ocr_text: string;
  cleaned_ocr_text_length: number;
  content_source: string;
}

function sessionQuery(sessionId: string) {
  return `session_id=${encodeURIComponent(sessionId)}`;
}

export const authApi = {
  importBrowserLogin: (cookieSource = "auto", forceRefresh = true) =>
    request<AuthSessionResponse>("/auth/login/browser", {
      method: "POST",
      body: JSON.stringify({ cookie_source: cookieSource, force_refresh: forceRefresh }),
    }),
  startQRCode: () => request<QrLoginStartResponse>("/auth/login/qrcode", { method: "POST" }),
  pollQRCode: (loginId: string) => request<QrLoginStatusResponse>(`/auth/login/qrcode/status/${loginId}`),
  getSession: (sessionId: string) => request<AuthSessionResponse>(`/auth/session/${sessionId}`),
  logout: (sessionId: string) =>
    request<{ message: string }>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
};

export const collectionsApi = {
  list: (sessionId: string) => request<CollectionSummary[]>(`/collections/list?${sessionQuery(sessionId)}`),
  getItems: (sourceType: string, sessionId: string) =>
    request<CollectionItemsResponse>(`/collections/${sourceType}/items?${sessionQuery(sessionId)}`),
};

export const knowledgeApi = {
  getStatus: (sessionId: string) => request<KnowledgeStatusResponse>(`/knowledge/status?${sessionQuery(sessionId)}`),
  startSync: (
    sessionId: string,
    payload: { source_type?: string; max_items_per_source: number; force_refresh: boolean; force_reindex: boolean },
  ) =>
    request<SyncStartResponse>(`/knowledge/sync?${sessionQuery(sessionId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSyncStatus: (taskId: string) => request<SyncTaskStatusResponse>(`/knowledge/sync/status/${taskId}`),
  retrySync: (taskId: string, sessionId: string) =>
    request<SyncStartResponse>(`/knowledge/sync/retry/${taskId}?${sessionQuery(sessionId)}`, {
      method: "POST",
    }),
  startIndexTask: (
    sessionId: string,
    payload: { note_ids?: string[]; source_type?: string; force_reindex?: boolean },
  ) =>
    request<SyncStartResponse>(`/knowledge/index/task?${sessionQuery(sessionId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getIndexTaskStatus: (taskId: string) => request<SyncTaskStatusResponse>(`/knowledge/index/status/${taskId}`),
  retryIndexTask: (taskId: string, sessionId: string) =>
    request<SyncStartResponse>(`/knowledge/index/retry/${taskId}?${sessionQuery(sessionId)}`, {
      method: "POST",
    }),
};

export const chatApi = {
  search: (
    sessionId: string,
    payload: { question: string; k: number; note_ids?: string[]; source_type?: string },
  ) =>
    request<ChatSearchResponse>(`/chat/search?${sessionQuery(sessionId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ask: (
    sessionId: string,
    payload: { question: string; k: number; note_ids?: string[]; source_type?: string },
  ) =>
    request<ChatResponse>(`/chat/ask?${sessionQuery(sessionId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  stream: async (
    sessionId: string,
    payload: { question: string; k: number; note_ids?: string[]; source_type?: string },
    handlers: {
      onEvent: (event: ChatStreamEvent) => void;
      onError?: (message: string) => void;
    },
    signal?: AbortSignal,
  ) => {
    const response = await fetch(`${API_BASE_URL}/chat/stream?${sessionQuery(sessionId)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal,
    });

    if (!response.ok || !response.body) {
      const text = await response.text();
      throw new Error(text || `请求失败: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes("\n\n")) {
        const boundary = buffer.indexOf("\n\n");
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const lines = rawEvent.split("\n");
        let eventName = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            data += line.slice(5).trim();
          }
        }

        if (!data) {
          continue;
        }

        try {
          const parsed = JSON.parse(data) as ChatStreamEvent;
          handlers.onEvent({ ...parsed, type: (parsed.type || eventName) as ChatStreamEvent["type"] });
        } catch {
          handlers.onError?.("流式响应解析失败");
        }
      }
    }
  },
};

export const notesApi = {
  get: (sessionId: string, noteId: string) => request<CachedNoteResponse>(`/notes/${noteId}?${sessionQuery(sessionId)}`),
  cache: (
    sessionId: string,
    noteId: string,
    payload: { source_type?: string; xsec_token?: string; note_url?: string; force_refresh?: boolean },
  ) =>
    request<CachedNoteResponse>(`/notes/${noteId}/cache?${sessionQuery(sessionId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getContent: (sessionId: string, noteId: string) =>
    request<ExtractedContentResponse>(`/notes/${noteId}/content?${sessionQuery(sessionId)}`),
  getOCR: (sessionId: string, noteId: string) =>
    request<NoteOcrResponse>(`/notes/${noteId}/ocr?${sessionQuery(sessionId)}`),
};
