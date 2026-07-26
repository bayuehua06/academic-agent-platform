"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DraftViewer } from "@/components/DraftViewer";
import { ProjectInputs } from "@/components/ProjectInputs";
import { VersionHistory } from "@/components/VersionHistory";
import { ZoteroList } from "@/components/ZoteroList";
import {
  apiFetch,
  downloadExport,
  DraftVersion,
  listSources,
  Literature,
  Project,
  SourceDocument,
} from "@/lib/api";
import { STATUS_LABELS, statusColor } from "@/lib/utils";

type Tab = "inputs" | "literature" | "draft";

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  const [tab, setTab] = useState<Tab>("inputs");
  const [project, setProject] = useState<Project | null>(null);
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [literatures, setLiteratures] = useState<Literature[]>([]);
  const [drafts, setDrafts] = useState<DraftVersion[]>([]);
  const [selectedDraft, setSelectedDraft] = useState<DraftVersion | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadAll = useCallback(async () => {
    const [p, srcs, lits, vers] = await Promise.all([
      apiFetch<Project>(`/projects/${projectId}`),
      listSources(projectId),
      apiFetch<Literature[]>(`/zotero/projects/${projectId}/literatures`),
      apiFetch<DraftVersion[]>(`/drafts/${projectId}`),
    ]);
    setProject(p);
    setSources(srcs);
    setLiteratures(lits);
    setDrafts(vers);
    setSelectedDraft((prev) => {
      if (prev && vers.some((v) => v.id === prev.id)) {
        return vers.find((v) => v.id === prev.id) || vers[0] || null;
      }
      return vers[0] || null;
    });
  }, [projectId]);

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login");
      return;
    }
    loadAll().catch((err) => setError(err.message));
  }, [loadAll, router]);

  async function runAgent() {
    if (!project?.assessment_ready) {
      setError("请先添加 Assessment（A）材料并生成定稿摘要");
      setTab("inputs");
      return;
    }
    if (!project?.outline_ready) {
      setError("请先上传论文大纲（C）并点击「锁定」");
      setTab("inputs");
      return;
    }

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

  const canRun = Boolean(project.assessment_ready && project.outline_ready);

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
          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              className="btn"
              onClick={runAgent}
              disabled={busy || !canRun}
              title={canRun ? "运行学术 Agent" : "需先完成 A 定稿并锁定 C 大纲"}
            >
              运行学术 Agent
            </button>
            {!canRun && (
              <p className="text-xs text-stone-500">需 A 就绪 + C 已锁定</p>
            )}
          </div>
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
          <ProjectInputs
            projectId={projectId}
            project={project}
            sources={sources}
            busy={busy}
            setBusy={setBusy}
            onMessage={setMessage}
            onError={setError}
            onReload={loadAll}
          />
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
