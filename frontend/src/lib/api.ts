const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:1976/api";

export type Project = {
  id: string;
  user_id: string;
  title: string;
  assessment_summary?: string | null;
  paper_outline?: OutlineItem[] | null;
  outline_locked_at?: string | null;
  specific_requirements?: string | null;
  confirmed_facts?: string | null;
  zotero_collection_id?: string | null;
  zotero_binding_mode?: "create" | "attach" | string | null;
  zotero_library_type?: "user" | "group" | string | null;
  zotero_library_id?: string | null;
  literature_databases?: string[] | null;
  status: string;
  created_at: string;
  updated_at: string;
  literature_count: number;
  source_document_count?: number;
  latest_version?: number | null;
  outline_ready?: boolean;
  assessment_ready?: boolean;
};

export type OutlineItem = {
  level: number;
  heading: string;
  key_points?: string;
};

export type SourceRole = "ASSESSMENT" | "BACKGROUND" | "OUTLINE" | "SPECIFIC";

export type SourceDocument = {
  id: string;
  project_id: string;
  role: SourceRole | string;
  source_type: string;
  title?: string | null;
  notebook_url?: string | null;
  original_filename?: string | null;
  content_type?: string | null;
  storage_path?: string | null;
  raw_text?: string | null;
  summary_text?: string | null;
  summary_json?: OutlineItem[] | null;
  status: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  summarized_at?: string | null;
};

export type Literature = {
  id: string;
  project_id: string;
  zotero_item_key?: string | null;
  zotero_subcollection_key?: string | null;
  outline_heading?: string | null;
  source_query?: string | null;
  title: string;
  authors?: string[] | null;
  year?: string | null;
  doi?: string | null;
  abstract?: string | null;
  landing_url?: string | null;
  evidence_tier?: string | null;
  evidence_source?: string | null;
  evidence_fetched_at?: string | null;
  relevance_score?: number | null;
  selected_for_draft: boolean;
  confirmed_at?: string | null;
  created_at: string;
  assigned_headings?: string[];
  collection_path?: string | null;
};

export type LiteratureCandidate = {
  title: string;
  authors?: string[];
  year?: string | null;
  doi?: string | null;
  abstract?: string | null;
  url?: string | null;
  provider?: string;
  outline_heading?: string;
  source_query?: string;
  relevance_score?: number | null;
  /** 已在本项目 Zotero Collection（任意子集合）中 */
  already_exists?: boolean;
  existing_outline_heading?: string | null;
  existing_zotero_item_key?: string | null;
};

export type LiteratureProvider = {
  id: string;
  name: string;
  entry_url: string;
  implemented: boolean;
};

export type LiteratureSearchRun = {
  id: string;
  project_id: string;
  outline_heading: string;
  query: string;
  providers: string[];
  status: string;
  error?: string | null;
  candidates: LiteratureCandidate[];
  created_at: string;
  partial_errors?: { provider: string; error: string }[] | null;
  deduped_count?: number | null;
};

export type DraftVersion = {
  id: string;
  project_id: string;
  version_number: number;
  major?: number | null;
  minor?: number;
  display_label: string;
  parent_version_id?: string | null;
  base_version_id?: string | null;
  content_markdown: string;
  apa_references_block?: string | null;
  source_type: string;
  changelog?: string | null;
  created_at: string;
  citation_warnings?: string[] | null;
  directives_persisted?: number | null;
  references_matched?: number | null;
  verify_ok?: boolean | null;
  verification_issues?: string[];
  repair_available?: boolean;
  writer_word_count?: number | null;
  writer_word_target?: { min?: number; max?: number } | null;
  repaired?: boolean;
};

export type DraftWorking = {
  id: string;
  project_id: string;
  base_version_id: string;
  base_display_label?: string | null;
  content_markdown: string;
  section_overrides?: Record<string, string> | null;
  pending_directives?: unknown[] | null;
  working_facts?: string | null;
  stale_headings?: string[] | null;
  status: string;
  source_filename?: string | null;
  created_at: string;
  updated_at: string;
  outline_seeds?: Record<string, string> | null;
  sections?: {
    heading: string;
    level: number;
    status: string;
    similarity: number;
    has_locked_blocks: boolean;
    locked_count: number;
    polished: boolean;
  }[];
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
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail?.message) detail = body.detail.message;
      else if (body.detail) detail = JSON.stringify(body.detail);
      else detail = JSON.stringify(body);
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

export async function listSources(projectId: string, role?: SourceRole) {
  const q = role ? `?role=${role}` : "";
  return apiFetch<SourceDocument[]>(`/projects/${projectId}/sources${q}`);
}

export async function pasteSource(
  projectId: string,
  payload: { role: SourceRole; raw_text: string; title?: string },
) {
  return apiFetch<SourceDocument>(`/projects/${projectId}/sources`, {
    method: "POST",
    body: JSON.stringify({
      role: payload.role,
      source_type: "PASTE",
      title: payload.title,
      raw_text: payload.raw_text,
    }),
  });
}

export async function uploadSource(
  projectId: string,
  role: SourceRole,
  file: File,
  title?: string,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("role", role);
  if (title) form.append("title", title);
  return apiFetch<SourceDocument>(`/projects/${projectId}/sources/upload`, {
    method: "POST",
    body: form,
  });
}

export async function deleteSource(projectId: string, sourceId: string) {
  return apiFetch<void>(`/projects/${projectId}/sources/${sourceId}`, {
    method: "DELETE",
  });
}

export async function summarizeSource(projectId: string, sourceId: string) {
  return apiFetch<SourceDocument>(
    `/projects/${projectId}/sources/${sourceId}/summarize`,
    { method: "POST" },
  );
}

export async function lockOutline(projectId: string, sourceId?: string) {
  return apiFetch<SourceDocument>(`/projects/${projectId}/outline/lock`, {
    method: "POST",
    body: JSON.stringify(sourceId ? { source_id: sourceId } : {}),
  });
}

export async function syncNotebook(projectId: string, notebookUrl: string) {
  return apiFetch<SourceDocument>(`/projects/${projectId}/sources/notebook-sync`, {
    method: "POST",
    body: JSON.stringify({ notebook_url: notebookUrl, use_browser: true }),
  });
}

export function exportUrl(projectId: string, format: "docx" | "pdf") {
  const token = getToken();
  return `${API_URL}/drafts/${projectId}/export?format=${format}&token=${token || ""}`;
}

function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return star[1].trim();
    }
  }
  const plain = /filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i.exec(header);
  const name = (plain?.[1] || plain?.[2] || "").trim();
  return name || fallback;
}

/** 本地拼下载名：项目名_v版本.ext（与后端 sanitize 规则对齐） */
export function buildExportFilename(
  title: string | undefined | null,
  versionLabel: string | number | undefined | null,
  format: "docx" | "pdf",
): string {
  let cleaned = (title || "draft").trim() || "draft";
  cleaned = cleaned.replace(/[\\/:*?"<>|\r\n\t]+/g, "_").replace(/\s+/g, "_").replace(/_+/g, "_");
  cleaned = cleaned.replace(/^[._]+|[._]+$/g, "").slice(0, 80) || "draft";
  const ver = String(versionLabel || "1").replace(/[\\/:*?"<>|\s]+/g, "_");
  return `${cleaned}_v${ver}.${format}`;
}

/** 带鉴权下载文件（文件名：响应头优先，否则用 suggestedFilename） */
export async function downloadExport(
  projectId: string,
  format: "docx" | "pdf",
  suggestedFilename?: string,
  versionId?: string,
) {
  const token = getToken();
  const qs = new URLSearchParams({ format });
  if (versionId) qs.set("version_id", versionId);
  const res = await fetch(`${API_URL}/drafts/${projectId}/export?${qs}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("导出失败");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameFromContentDisposition(
    res.headers.get("Content-Disposition"),
    suggestedFilename || `draft.${format}`,
  );
  a.click();
  URL.revokeObjectURL(url);
}

export { API_URL };
