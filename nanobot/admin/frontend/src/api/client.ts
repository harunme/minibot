const TOKEN_KEY = "nanobot_admin_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

function apiBase(): string {
  // In production served at /admin/*, API is at same origin
  return "";
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${apiBase()}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error((body as { error?: string }).error || `HTTP ${res.status}`);
  }

  return res.json() as Promise<T>;
}

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface DocumentMeta {
  id: string;
  content_preview: string;
  metadata: {
    source?: string;
    category?: string;
    file_name?: string;
    chunk_index?: number;
    total_chunks?: number;
    [key: string]: unknown;
  };
}

export interface DocumentListResponse {
  documents: DocumentMeta[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentDetail {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
}

export interface CollectionStats {
  count: number;
  categories: Record<string, number>;
  storage_bytes: number | null;
}

export interface SearchResult {
  id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  total: number;
}

export interface UploadResponse {
  file_name: string;
  total_pages: number;
  chunks_created: number;
  doc_ids: string[];
}

// ─── API Client ────────────────────────────────────────────────────────────────

export const api = {
  listDocuments(params: {
    category?: string;
    limit?: number;
    offset?: number;
  }): Promise<DocumentListResponse> {
    const qs = new URLSearchParams();
    if (params.category) qs.set("category", params.category);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return request(`/api/admin/documents?${qs}`);
  },

  getDocument(id: string): Promise<DocumentDetail> {
    return request(`/api/admin/documents/${encodeURIComponent(id)}`);
  },

  deleteDocument(id: string): Promise<{ deleted: boolean; id: string }> {
    return request(`/api/admin/documents/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  batchDeleteDocuments(ids: string[]): Promise<{ deleted: number; ids: string[] }> {
    return request(`/api/admin/documents`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
  },

  uploadDocument(
    file: File,
    category: string
  ): Promise<UploadResponse> {
    const form = new FormData();
    form.append("file", file);
    form.append("category", category);
    return request(`/api/admin/documents/upload`, {
      method: "POST",
      body: form,
    });
  },

  getStats(): Promise<CollectionStats> {
    return request("/api/admin/documents/stats");
  },

  search(params: {
    q: string;
    top_k?: number;
    category?: string;
  }): Promise<SearchResponse> {
    const qs = new URLSearchParams({ q: params.q });
    if (params.top_k != null) qs.set("top_k", String(params.top_k));
    if (params.category) qs.set("category", params.category);
    return request(`/api/admin/search?${qs}`);
  },
};
