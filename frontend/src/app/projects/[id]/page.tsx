"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { DraftViewer } from "@/components/DraftViewer";
import { VersionHistory } from "@/components/VersionHistory";
import { ZoteroList } from "@/components/ZoteroList";
import {
  apiFetch,
  downloadExport,
  DraftVersion,
  Literature,
  NotebookInput,
  Project,
} from "@/lib/api";
import { formatDate, STATUS_LABELS, statusColor } from "@/lib/utils";

type Tab = "inputs" | "literature" | "draft";

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  const [tab, setTab] = useState<Tab>("inputs");
  const [project, setProject] = useState<Project | null>(null);
  const [notebooks, setNotebooks] = useState<NotebookInput[]>([]);
  const [literatures, setLiteratures] = useState<Literature[]>([]);
  const [drafts, setDrafts] = useState<DraftVersion[]>([]);
  const [selectedDraft, setSelectedDraft] = useState<DraftVersion | null>(null);
  const [assessment, setAssessment] = useState("");
  const [transcript, setTranscript] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadAll = useCallback(async () => {
    const [p, nbs, lits, vers] = await Promise.all([
      apiFetch<Project>(`/projects/${projectId}`),
      apiFetch<NotebookInput[]>(`/notebook/${projectId}`),
      apiFetch<Literature[]>(`/zotero/projects/${projectId}/literatures`),
      apiFetch<DraftVersion[]>(`/drafts/${projectId}`),
    ]);
    setProject(p);
    setAssessment(p.assessment_requirements || "");
    setNotebooks(nbs);
    setLiteratures(lits);
    setDrafts(vers);
    setSelectedDraft(vers[0] || null);
  }, [projectId]);

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login");
      return;
    }
    loadAll().catch((err) => setError(err.message));
  }, [loadAll, router]);

  async function saveAssessment(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const p = await apiFetch<Project>(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ assessment_requirements: assessment }),
      });
      setProject(p);
      setMessage("Assessment 已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function syncNotebook(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/notebook/${projectId}`, {
        method: "POST",
        body: JSON.stringify({ raw_transcript: transcript }),
      });
      setTranscript("");
      setMessage("NotebookLM 输入已同步");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "同步失败");
    } finally {
      setBusy(false);
    }
  }

  async function runAgent() {
    setBusy(true);
    setError("");
    setMessage("Agent 运行中…");
    try {
      const draft = await apiFetch<DraftVersion>(`/projects/${projectId}/run-agent`, {
        method: "POST",
        body: JSON.stringify({ max_papers: 5, skip_search: false }),
      });
      setMessage(`已生成草稿 v${draft.version_number}`);
      setTab("draft");
      await loadAll();
      setSelectedDraft(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent 失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleLit(id: string, selected: boolean) {
    await apiFetch(`/zotero/literatures/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ selected_for_draft: selected }),
    });
    setLiteratures((prev) =>
      prev.map((l) => (l.id === id ? { ...l, selected_for_draft: selected } : l)),
    );
  }

  async function onImportDocx(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const token = localStorage.getItem("access_token");
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:1976/api"}/drafts/import-docx?project_id=${projectId}`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "导入失败");
      }
      const draft = (await res.json()) as DraftVersion;
      setMessage(`已导入为 v${draft.version_number}`);
      await loadAll();
      setSelectedDraft(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-12">
        <p className="text-sm text-stone-500">{error || "加载中…"}</p>
      </main>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "inputs", label: "Inputs & Assessment" },
    { id: "literature", label: "Literature Library" },
    { id: "draft", label: "Draft & Versions" },
  ];

  return (
    <main className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div>
            <Link href="/dashboard" className="text-xs text-brand-600 underline">
              ← 返回看板
            </Link>
            <h1 className="font-display text-2xl font-bold text-brand-700">{project.title}</h1>
            <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${statusColor(project.status)}`}>
              {STATUS_LABELS[project.status] || project.status}
            </span>
          </div>
          <button type="button" className="btn" onClick={runAgent} disabled={busy}>
            运行学术 Agent
          </button>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 px-4">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-4 py-2 text-sm ${
                tab === t.id
                  ? "border-brand-600 font-medium text-brand-700"
                  : "border-transparent text-stone-500 hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="mx-auto max-w-5xl px-4 py-6">
        {(message || error) && (
          <p className={`mb-4 text-sm ${error ? "text-accent" : "text-brand-600"}`}>
            {error || message}
          </p>
        )}

        {tab === "inputs" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <form onSubmit={saveAssessment} className="card space-y-3">
              <h2 className="font-display text-lg font-semibold">Assessment 要求</h2>
              <textarea
                className="input min-h-[180px]"
                value={assessment}
                onChange={(e) => setAssessment(e.target.value)}
                placeholder="粘贴课程作业 / 评估要求…"
              />
              <button type="submit" className="btn" disabled={busy}>
                保存
              </button>
            </form>
            <form onSubmit={syncNotebook} className="card space-y-3">
              <h2 className="font-display text-lg font-semibold">NotebookLM 输入</h2>
              <textarea
                className="input min-h-[180px]"
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder="粘贴 NotebookLM 对话 / 笔记…"
              />
              <button type="submit" className="btn" disabled={busy || !transcript.trim()}>
                同步要点
              </button>
              {notebooks[0] && (
                <div className="mt-4 rounded-md bg-stone-50 p-3 text-sm">
                  <p className="text-xs text-stone-400">
                    最近同步 {formatDate(notebooks[0].synced_at)}
                  </p>
                  <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs text-stone-600">
                    {notebooks[0].extracted_summary || notebooks[0].raw_transcript}
                  </pre>
                </div>
              )}
            </form>
          </div>
        )}

        {tab === "literature" && (
          <div className="card">
            <h2 className="mb-4 font-display text-lg font-semibold">
              文献库（Zotero 同步）
            </h2>
            <ZoteroList items={literatures} onToggle={toggleLit} />
          </div>
        )}

        {tab === "draft" && (
          <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
            <aside className="card">
              <h2 className="mb-3 font-display text-base font-semibold">版本历史</h2>
              <VersionHistory
                versions={drafts}
                selectedId={selectedDraft?.id}
                onSelect={setSelectedDraft}
              />
              <div className="mt-4 space-y-2 border-t border-stone-100 pt-4">
                <button
                  type="button"
                  className="btn-outline w-full text-xs"
                  disabled={!selectedDraft || busy}
                  onClick={() => downloadExport(projectId, "docx")}
                >
                  下载 DOCX
                </button>
                <button
                  type="button"
                  className="btn-outline w-full text-xs"
                  disabled={!selectedDraft || busy}
                  onClick={() => downloadExport(projectId, "pdf").catch((e) => setError(e.message))}
                >
                  下载 PDF
                </button>
                <label className="btn-outline w-full cursor-pointer text-xs">
                  上传 Word 导入
                  <input
                    type="file"
                    accept=".docx"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onImportDocx(f);
                    }}
                  />
                </label>
              </div>
            </aside>
            <DraftViewer draft={selectedDraft} />
          </div>
        )}
      </div>
    </main>
  );
}
