const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:1976/api";

export type Project = {
  id: string;
  user_id: string;
  title: string;
  assessment_requirements?: string | null;
  zotero_collection_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  literature_count: number;
  latest_version?: number | null;
  latest_sync_at?: string | null;
};

export type Literature = {
  id: string;
  project_id: string;
  zotero_item_key?: string | null;
  title: string;
  authors?: string[] | null;
  year?: string | null;
  doi?: string | null;
  abstract?: string | null;
  relevance_score?: number | null;
  selected_for_draft: boolean;
  created_at: string;
};

export type DraftVersion = {
  id: string;
  project_id: string;
  version_number: number;
  content_markdown: string;
  apa_references_block?: string | null;
  source_type: string;
  changelog?: string | null;
  created_at: string;
};

export type NotebookInput = {
  id: string;
  project_id: string;
  notebook_url?: string | null;
  raw_transcript?: string | null;
  extracted_summary?: string | null;
  synced_at: string;
};

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function setToken(token: string) {
  localStorage.setItem("access_token", token);
}

export function clearToken() {
  localStorage.removeItem("access_token");
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "登录失败");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

export async function register(username: string, email: string, password: string) {
  return apiFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, email, password }),
  });
}

export function exportUrl(projectId: string, format: "docx" | "pdf") {
  const token = getToken();
  return `${API_URL}/drafts/${projectId}/export?format=${format}&token=${token || ""}`;
}

/** 带鉴权下载文件 */
export async function downloadExport(projectId: string, format: "docx" | "pdf") {
  const token = getToken();
  const res = await fetch(`${API_URL}/drafts/${projectId}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("导出失败");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `draft.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}

export { API_URL };
