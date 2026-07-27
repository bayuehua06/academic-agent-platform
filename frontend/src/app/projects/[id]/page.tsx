"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Download, Sparkles, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DraftViewer } from "@/components/DraftViewer";
import { DraftPolishPanel } from "@/components/DraftPolishPanel";
import { LiteratureConfirmPanel } from "@/components/LiteratureConfirmPanel";
import { ProjectInputs } from "@/components/ProjectInputs";
import { SectionDirectivesPanel } from "@/components/SectionDirectivesPanel";
import { VersionHistory } from "@/components/VersionHistory";
import {
  apiFetch,
  downloadExport,
  buildExportFilename,
  DraftVersion,
  DraftWorking,
  listSources,
  Literature,
  Project,
  SourceDocument,
} from "@/lib/api";
import { STATUS_LABELS, statusColor } from "@/lib/utils";

type Tab = "inputs" | "literature" | "draft";

function WordBadge() {
  return (
    <span
      className="inline-flex h-5 min-w-5 items-center justify-center rounded bg-[#2B579A] px-0.5 text-[10px] font-bold leading-none text-white"
      aria-hidden
    >
      W
    </span>
  );
}

function PdfBadge() {
  return (
    <span
      className="inline-flex h-5 min-w-5 items-center justify-center rounded bg-[#E5252A] px-0.5 text-[8px] font-bold leading-none text-white"
      aria-hidden
    >
      PDF
    </span>
  );
}

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
  const [working, setWorking] = useState<DraftWorking | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const loadAll = useCallback(async () => {
    const [p, srcs, lits, vers, wrk] = await Promise.all([
      apiFetch<Project>(`/projects/${projectId}`),
      listSources(projectId),
      apiFetch<Literature[]>(`/zotero/projects/${projectId}/literatures`),
      apiFetch<DraftVersion[]>(`/drafts/${projectId}`),
      apiFetch<DraftWorking | null>(`/drafts/${projectId}/working`),
    ]);
    setProject(p);
    setSources(srcs);
    setLiteratures(lits);
    setDrafts(vers);
    setWorking(wrk);
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

  async function saveTitle() {
    const next = titleDraft.trim();
    if (!next || !project) return;
    if (next === project.title) {
      setEditingTitle(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await apiFetch<Project>(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: next }),
      });
      setProject(updated);
      setEditingTitle(false);
      setMessage("已更新项目标题");
    } catch (err) {
      setError(err instanceof Error ? err.message : "改名失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteProject() {
    if (!project) return;
    const ok = window.confirm(
      `确定删除项目「${project.title}」？本地文献镜像与草稿将一并删除（Zotero 远端集合不会自动删）。`,
    );
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
      setBusy(false);
    }
  }

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
        body: JSON.stringify({ max_papers: 5, skip_search: true }),
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
    if (!selectedDraft) {
      setError("请先选择一个已确认版本作为上传基础（base）");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const token = localStorage.getItem("access_token");
      const qs = new URLSearchParams({
        project_id: projectId,
        base_version_id: selectedDraft.id,
      });
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:1976/api"}/drafts/import-docx?${qs}`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          typeof body.detail === "string" ? body.detail : "导入失败",
        );
      }
      const wrk = (await res.json()) as DraftWorking;
      setWorking(wrk);
      setMessage(
        `已上传到精修工作区（基于 v${wrk.base_display_label || selectedDraft.display_label}）。确认后才会生成小版本。`,
      );
      setTab("draft");
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function startPolishFromSelected() {
    if (!selectedDraft) {
      setError("请先选择一个版本作为精修基础");
      return;
    }
    if (working && !confirm("已有未确认工作区，开启新精修将丢弃它。继续？")) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const wrk = await apiFetch<DraftWorking>(
        `/drafts/${projectId}/working/start?base_version_id=${selectedDraft.id}`,
        { method: "POST" },
      );
      setWorking(wrk);
      setMessage(
        `已基于 v${wrk.base_display_label || selectedDraft.display_label} 开启精修工作区（无需上传）`,
      );
      setTab("draft");
    } catch (err) {
      setError(err instanceof Error ? err.message : "开启精修失败");
    } finally {
      setBusy(false);
    }
  }

  async function confirmWorking() {
    setBusy(true);
    setError("");
    try {
      const draft = await apiFetch<DraftVersion>(
        `/drafts/${projectId}/working/confirm`,
        { method: "POST" },
      );
      const bits = [`已确认精修 → v${draft.display_label}`];
      if (draft.directives_persisted) {
        bits.push(`落库指令 ${draft.directives_persisted} 条`);
      }
      if (draft.references_matched != null) {
        bits.push(`References 匹配 ${draft.references_matched}`);
      }
      if (draft.citation_warnings?.length) {
        bits.push(`未匹配引用 ${draft.citation_warnings.length}（已警告）`);
      }
      setMessage(bits.join(" · "));
      await loadAll();
      setSelectedDraft(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  async function discardWorking() {
    if (!confirm("确定丢弃当前精修工作区？未确认的修改将丢失。")) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/drafts/${projectId}/working`, { method: "DELETE" });
      setWorking(null);
      setMessage("已丢弃精修工作区");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "丢弃失败");
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
            {editingTitle ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <input
                  className="input max-w-md"
                  value={titleDraft}
                  disabled={busy}
                  autoFocus
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveTitle();
                    if (e.key === "Escape") setEditingTitle(false);
                  }}
                />
                <button type="button" className="btn text-sm" disabled={busy} onClick={() => void saveTitle()}>
                  保存
                </button>
                <button
                  type="button"
                  className="btn-outline text-sm"
                  disabled={busy}
                  onClick={() => setEditingTitle(false)}
                >
                  取消
                </button>
              </div>
            ) : (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h1 className="font-display text-2xl font-bold text-brand-700">{project.title}</h1>
                <button
                  type="button"
                  className="btn-outline text-xs"
                  disabled={busy}
                  onClick={() => {
                    setTitleDraft(project.title);
                    setEditingTitle(true);
                  }}
                >
                  改名
                </button>
                <button
                  type="button"
                  className="btn-outline text-xs text-red-700 hover:border-red-400"
                  disabled={busy}
                  onClick={() => void deleteProject()}
                >
                  删除
                </button>
              </div>
            )}
            <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${statusColor(project.status)}`}>
              {STATUS_LABELS[project.status] || project.status}
            </span>
          </div>          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              className="btn"
              onClick={runAgent}
              disabled={busy || !canRun}
              title={
                canRun
                  ? "运行学术 Agent"
                  : "需 A 定稿 + C 锁定"
              }
            >
              运行学术 Agent
            </button>
            {!canRun && (
              <p className="text-xs text-stone-500">需 A 定稿 + 锁定大纲（文献可选）</p>
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
          <LiteratureConfirmPanel
            projectId={projectId}
            project={project}
            literatures={literatures}
            busy={busy}
            setBusy={setBusy}
            onMessage={setMessage}
            onError={setError}
            onReload={loadAll}
            onToggleLit={toggleLit}
          />
        )}

        {tab === "draft" && (
          <div className="space-y-4">
            <div className="card flex flex-wrap items-center gap-2 py-3">
              <button
                type="button"
                className="btn-outline gap-1.5 px-3 py-1.5 text-xs"
                disabled={!selectedDraft || busy}
                title="下载 Word"
                onClick={() =>
                  downloadExport(
                    projectId,
                    "docx",
                    buildExportFilename(project?.title, selectedDraft?.display_label, "docx"),
                    selectedDraft?.id,
                  ).catch((e) => setError(e.message))
                }
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                <WordBadge />
                <span>Word</span>
              </button>
              <button
                type="button"
                className="btn-outline gap-1.5 px-3 py-1.5 text-xs"
                disabled={!selectedDraft || busy}
                title="下载 PDF"
                onClick={() =>
                  downloadExport(
                    projectId,
                    "pdf",
                    buildExportFilename(project?.title, selectedDraft?.display_label, "pdf"),
                    selectedDraft?.id,
                  ).catch((e) => setError(e.message))
                }
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                <PdfBadge />
                <span>PDF</span>
              </button>
              <button
                type="button"
                className="btn-outline gap-1.5 px-3 py-1.5 text-xs"
                disabled={!selectedDraft || busy}
                title="基于当前选中版本开启精修（无需上传）"
                onClick={() => startPolishFromSelected()}
              >
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                <span>精修</span>
              </button>
              <label
                className={`btn-outline gap-1.5 px-3 py-1.5 text-xs ${
                  busy ? "pointer-events-none opacity-50" : "cursor-pointer"
                }`}
                title="上传 Word（基于当前选中版本，进入精修工作区）"
              >
                <Upload className="h-3.5 w-3.5" aria-hidden />
                <WordBadge />
                <span>导入</span>
                <input
                  type="file"
                  accept=".docx"
                  className="hidden"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) onImportDocx(f);
                    e.target.value = "";
                  }}
                />
              </label>
              {selectedDraft && (
                <span className="ml-auto text-xs text-stone-500">
                  当前：v{selectedDraft.display_label}
                  {working ? " · 有未确认工作区" : ""}
                </span>
              )}
            </div>
            {working && (
              <div className="card flex flex-wrap items-center gap-3 border-amber-200 bg-amber-50 py-3">
                <p className="text-sm text-amber-900">
                  精修工作区（基于 v{working.base_display_label || "?"}
                  {working.source_filename ? ` · ${working.source_filename}` : ""}
                  ）。可分节对比与 AI 精修；确认后生成小版本。
                </p>
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    className="btn-outline px-3 py-1.5 text-xs"
                    disabled={busy}
                    onClick={() => discardWorking()}
                  >
                    丢弃
                  </button>
                  <button
                    type="button"
                    className="btn px-3 py-1.5 text-xs"
                    disabled={busy}
                    onClick={() => confirmWorking()}
                  >
                    确认 → 小版本
                  </button>
                </div>
              </div>
            )}
            {working ? (
              <DraftPolishPanel
                projectId={projectId}
                working={working}
                literatures={literatures}
                busy={busy}
                setBusy={setBusy}
                onMessage={setMessage}
                onError={setError}
                onWorkingChange={setWorking}
              />
            ) : (
              <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
                <aside className="card">
                  <h2 className="mb-3 font-display text-base font-semibold">版本历史</h2>
                  <VersionHistory
                    versions={drafts}
                    selectedId={selectedDraft?.id}
                    onSelect={setSelectedDraft}
                  />
                </aside>
                <div className="space-y-4">
                  <DraftViewer draft={selectedDraft} />
                  <SectionDirectivesPanel
                    projectId={projectId}
                    busy={busy}
                    setBusy={setBusy}
                    onMessage={setMessage}
                    onError={setError}
                    refreshKey={selectedDraft?.id || drafts.length}
                  />
                </div>
              </div>
            )}
            {working && (
              <aside className="card">
                <h2 className="mb-3 font-display text-base font-semibold">版本历史</h2>
                <VersionHistory
                  versions={drafts}
                  selectedId={selectedDraft?.id}
                  onSelect={setSelectedDraft}
                />
              </aside>
            )}
            {working && (
              <SectionDirectivesPanel
                projectId={projectId}
                busy={busy}
                setBusy={setBusy}
                onMessage={setMessage}
                onError={setError}
                refreshKey={working.updated_at}
              />
            )}
          </div>
        )}
      </div>
    </main>
  );
}
