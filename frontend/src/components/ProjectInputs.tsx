"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  deleteSource,
  lockOutline,
  OutlineItem,
  pasteSource,
  Project,
  SourceDocument,
  SourceRole,
  summarizeSource,
  syncNotebook,
  uploadSource,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";

type Props = {
  projectId: string;
  project: Project;
  sources: SourceDocument[];
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
  onReload: () => Promise<void>;
};

const ROLE_META: Record<
  SourceRole,
  { title: string; hint: string; accept: string }
> = {
  ASSESSMENT: {
    title: "A · Assessment / Rubric",
    hint: "粘贴或上传评分标准、作业说明（可多份）。",
    accept: ".md,.txt,.docx,.pdf",
  },
  BACKGROUND: {
    title: "B · 背景材料",
    hint: "可选。上传笔记/PDF，或从 NotebookLM URL 更新。",
    accept: ".md,.txt,.docx,.pdf",
  },
  OUTLINE: {
    title: "C · 论文大纲",
    hint: "上传带 Heading 的 Word，或粘贴 Markdown # 标题；预览后锁定。",
    accept: ".md,.txt,.docx",
  },
  SPECIFIC: {
    title: "D · 具体要求",
    hint: "字数、引用风格等额外约束（可选）。",
    accept: ".md,.txt,.docx,.pdf",
  },
};

/** 列表卡片预览字数（完整内容点「查看全部」） */
const PREVIEW_CHARS = 160;
const KEY_POINTS_PREVIEW = 80;

type FullViewState = {
  title: string;
  body: string;
  meta?: string;
};

function fullDocText(doc: SourceDocument): string {
  return (doc.summary_text || doc.raw_text || "").trim() || "（无内容）";
}

function previewText(doc: SourceDocument, max = PREVIEW_CHARS): string {
  const text = fullDocText(doc);
  if (text === "（无内容）") return text;
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function FullTextModal({
  view,
  onClose,
}: {
  view: FullViewState;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="full-text-title"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg border border-stone-200 bg-white shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-stone-100 px-4 py-3">
          <div className="min-w-0">
            <h3 id="full-text-title" className="font-display text-base font-semibold text-ink">
              {view.title}
            </h3>
            {view.meta ? (
              <p className="mt-0.5 text-xs text-stone-500">{view.meta}</p>
            ) : null}
          </div>
          <button type="button" className="btn-outline shrink-0 text-xs" onClick={onClose}>
            关闭
          </button>
        </div>
        <pre className="flex-1 overflow-y-auto whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed text-stone-700">
          {view.body}
        </pre>
        <div className="border-t border-stone-100 px-4 py-2 text-xs text-stone-400">
          共 {view.body.length.toLocaleString()} 字符 · Esc 关闭
        </div>
      </div>
    </div>
  );
}

function OutlineTree({
  items,
  onOpenFull,
}: {
  items: OutlineItem[];
  onOpenFull?: () => void;
}) {
  if (!items.length) {
    return <p className="text-xs text-stone-400">尚无标题结构</p>;
  }
  return (
    <div className="space-y-2">
      <ul className="space-y-1 text-sm">
        {items.map((item, idx) => (
          <li
            key={`${item.heading}-${idx}`}
            style={{ paddingLeft: `${Math.max(0, (item.level || 1) - 1) * 12}px` }}
            className="text-stone-700"
          >
            <span className="font-medium">{item.heading}</span>
            {item.key_points ? (
              <span className="ml-2 text-xs text-stone-400">
                {item.key_points.slice(0, KEY_POINTS_PREVIEW)}
                {item.key_points.length > KEY_POINTS_PREVIEW ? "…" : ""}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {onOpenFull ? (
        <button type="button" className="btn-outline text-xs" onClick={onOpenFull}>
          查看全部大纲
        </button>
      ) : null}
    </div>
  );
}

function formatOutlineFull(items: OutlineItem[]): string {
  if (!items.length) return "（尚无标题结构）";
  return items
    .map((item) => {
      const level = Math.max(1, Math.min(Number(item.level) || 1, 6));
      const head = `${"#".repeat(level)} ${item.heading || ""}`.trim();
      const points = (item.key_points || "").trim();
      return points ? `${head}\n${points}` : head;
    })
    .join("\n\n");
}

export function ProjectInputs({
  projectId,
  project,
  sources,
  busy,
  setBusy,
  onMessage,
  onError,
  onReload,
}: Props) {
  const [pasteByRole, setPasteByRole] = useState<Record<SourceRole, string>>({
    ASSESSMENT: "",
    BACKGROUND: "",
    OUTLINE: "",
    SPECIFIC: "",
  });
  const [notebookUrl, setNotebookUrl] = useState("");
  const [fullView, setFullView] = useState<FullViewState | null>(null);

  const byRole = useMemo(() => {
    const map: Record<SourceRole, SourceDocument[]> = {
      ASSESSMENT: [],
      BACKGROUND: [],
      OUTLINE: [],
      SPECIFIC: [],
    };
    for (const s of sources) {
      const role = s.role as SourceRole;
      if (map[role]) map[role].push(s);
    }
    return map;
  }, [sources]);

  const latestOutline = byRole.OUTLINE[0];
  const outlinePreview: OutlineItem[] =
    (latestOutline?.summary_json as OutlineItem[] | undefined) ||
    project.paper_outline ||
    [];

  async function wrap(action: () => Promise<void>, okMsg: string) {
    setBusy(true);
    onError("");
    try {
      await action();
      onMessage(okMsg);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function onPaste(role: SourceRole, e: FormEvent) {
    e.preventDefault();
    const raw = pasteByRole[role].trim();
    if (!raw) {
      onError("请先填写粘贴内容");
      return;
    }
    await wrap(async () => {
      await pasteSource(projectId, { role, raw_text: raw });
      setPasteByRole((prev) => ({ ...prev, [role]: "" }));
    }, `${ROLE_META[role].title} 已保存`);
  }

  async function onUpload(role: SourceRole, file: File | undefined) {
    if (!file) return;
    await wrap(async () => {
      await uploadSource(projectId, role, file);
    }, `已上传 ${file.name}`);
  }

  async function onDelete(doc: SourceDocument) {
    await wrap(async () => {
      await deleteSource(projectId, doc.id);
    }, "已删除源文档");
  }

  async function onSummarize(doc: SourceDocument) {
    await wrap(async () => {
      await summarizeSource(projectId, doc.id);
    }, "已重新摘要");
  }

  async function onLock(sourceId?: string) {
    await wrap(async () => {
      await lockOutline(projectId, sourceId);
    }, "大纲已锁定");
  }

  async function onNotebookSync() {
    if (!notebookUrl.trim()) {
      onError("请填写 NotebookLM URL");
      return;
    }
    await wrap(async () => {
      await syncNotebook(projectId, notebookUrl.trim());
    }, "NotebookLM 已同步为背景材料");
  }

  function openDocFull(doc: SourceDocument) {
    const body = fullDocText(doc);
    setFullView({
      title: doc.title || doc.original_filename || doc.source_type || "源文档",
      body,
      meta: `${doc.status}${doc.summarized_at ? ` · ${formatDate(doc.summarized_at)}` : ""} · 优先显示摘要，无摘要则原文`,
    });
  }

  function renderSourceList(role: SourceRole) {
    const docs = byRole[role];
    if (!docs.length) {
      return <p className="text-xs text-stone-400">暂无文档</p>;
    }
    return (
      <ul className="space-y-2">
        {docs.map((doc) => {
          const full = fullDocText(doc);
          const truncated = full.length > PREVIEW_CHARS;
          return (
            <li key={doc.id} className="rounded-md border border-stone-100 bg-stone-50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-ink">
                    {doc.title || doc.original_filename || doc.source_type}
                  </p>
                  <p className="text-xs text-stone-500">
                    {doc.status}
                    {doc.summarized_at ? ` · ${formatDate(doc.summarized_at)}` : ""}
                    {` · ${full.length.toLocaleString()} 字符`}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-outline text-xs"
                    disabled={busy}
                    onClick={() => openDocFull(doc)}
                  >
                    查看全部
                  </button>
                  {role !== "OUTLINE" && (
                    <button
                      type="button"
                      className="btn-outline text-xs"
                      disabled={busy}
                      onClick={() => onSummarize(doc)}
                    >
                      重摘要
                    </button>
                  )}
                  {role === "OUTLINE" && (
                    <button
                      type="button"
                      className="btn text-xs"
                      disabled={busy}
                      onClick={() => onLock(doc.id)}
                    >
                      锁定此大纲
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-outline text-xs text-accent"
                    disabled={busy}
                    onClick={() => onDelete(doc)}
                  >
                    删除
                  </button>
                </div>
              </div>
              <pre className="mt-2 max-h-24 overflow-y-auto whitespace-pre-wrap text-xs text-stone-600">
                {previewText(doc)}
              </pre>
              {truncated ? (
                <p className="mt-1 text-[11px] text-stone-400">
                  列表仅预览前 {PREVIEW_CHARS} 字符，点「查看全部」看完整内容
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  function renderRoleCard(role: SourceRole) {
    const meta = ROLE_META[role];
    return (
      <section key={role} className="card space-y-3">
        <div>
          <h2 className="font-display text-lg font-semibold">{meta.title}</h2>
          <p className="mt-1 text-xs text-stone-500">{meta.hint}</p>
        </div>

        {renderSourceList(role)}

        <form onSubmit={(e) => onPaste(role, e)} className="space-y-2 border-t border-stone-100 pt-3">
          <label className="label" htmlFor={`paste-${role}`}>
            粘贴文本
          </label>
          <textarea
            id={`paste-${role}`}
            className="input min-h-[100px]"
            value={pasteByRole[role]}
            onChange={(e) =>
              setPasteByRole((prev) => ({ ...prev, [role]: e.target.value }))
            }
            placeholder={role === "OUTLINE" ? "# Introduction\n\n## Methods\n" : "粘贴内容…"}
          />
          <div className="flex flex-wrap gap-2">
            <button type="submit" className="btn" disabled={busy || !pasteByRole[role].trim()}>
              保存粘贴
            </button>
            <label className="btn-outline cursor-pointer text-sm">
              上传文件
              <input
                type="file"
                accept={meta.accept}
                className="hidden"
                disabled={busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  onUpload(role, f);
                }}
              />
            </label>
          </div>
        </form>

        {role === "BACKGROUND" && (
          <div className="space-y-2 border-t border-stone-100 pt-3">
            <label className="label" htmlFor="notebook-url">
              NotebookLM URL
            </label>
            <input
              id="notebook-url"
              className="input"
              value={notebookUrl}
              onChange={(e) => setNotebookUrl(e.target.value)}
              placeholder="https://notebooklm.google.com/..."
            />
            <p className="text-xs text-stone-500">
              需先运行 <code className="rounded bg-stone-100 px-1">./scripts/start-chrome-debug.sh</code>{" "}
              并登录专用 Chrome。
            </p>
            <button
              type="button"
              className="btn"
              disabled={busy || !notebookUrl.trim()}
              onClick={onNotebookSync}
            >
              从 NotebookLM 更新
            </button>
          </div>
        )}

        {role === "OUTLINE" && (
          <div className="space-y-2 border-t border-stone-100 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium">标题预览</h3>
              <button
                type="button"
                className="btn"
                disabled={busy || byRole.OUTLINE.length === 0}
                onClick={() => onLock()}
              >
                锁定最新大纲
              </button>
            </div>
            <OutlineTree
              items={outlinePreview}
              onOpenFull={
                outlinePreview.length
                  ? () =>
                      setFullView({
                        title: "大纲全文",
                        body: formatOutlineFull(outlinePreview),
                        meta: "含各节 key_points",
                      })
                  : undefined
              }
            />
            <p className="text-xs text-stone-500">
              锁定状态：{" "}
              {project.outline_ready
                ? `已锁定（${formatDate(project.outline_locked_at)}）`
                : "未锁定"}
            </p>
          </div>
        )}
      </section>
    );
  }

  return (
    <div className="space-y-6">
      {fullView ? (
        <FullTextModal view={fullView} onClose={() => setFullView(null)} />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
          A 定稿：{project.assessment_ready ? "就绪" : "未就绪"}
        </div>
        <div className="rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
          C 大纲：{project.outline_ready ? "已锁定" : "未锁定"}
        </div>
        <div className="rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
          B 背景：{byRole.BACKGROUND.length} 条
        </div>
        <div className="rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
          D 要求：{project.specific_requirements ? "有" : "无"}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {renderRoleCard("ASSESSMENT")}
        {renderRoleCard("BACKGROUND")}
        {renderRoleCard("OUTLINE")}
        {renderRoleCard("SPECIFIC")}
      </div>

      <section className="card space-y-4">
        <h2 className="font-display text-lg font-semibold">定稿预览（只读）</h2>
        <div className="grid gap-4 lg:grid-cols-3">
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-stone-600">Assessment 摘要</h3>
              {project.assessment_summary ? (
                <button
                  type="button"
                  className="btn-outline text-xs"
                  onClick={() =>
                    setFullView({
                      title: "Assessment 定稿摘要",
                      body: project.assessment_summary || "",
                    })
                  }
                >
                  查看全部
                </button>
              ) : null}
            </div>
            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-stone-50 p-3 text-xs text-stone-700">
              {project.assessment_summary
                ? project.assessment_summary.length > PREVIEW_CHARS
                  ? `${project.assessment_summary.slice(0, PREVIEW_CHARS)}…`
                  : project.assessment_summary
                : "（尚未生成）"}
            </pre>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-stone-600">论文大纲</h3>
              {(project.paper_outline || []).length ? (
                <button
                  type="button"
                  className="btn-outline text-xs"
                  onClick={() =>
                    setFullView({
                      title: "锁定大纲全文",
                      body: formatOutlineFull(project.paper_outline || []),
                    })
                  }
                >
                  查看全部
                </button>
              ) : null}
            </div>
            <div className="max-h-48 overflow-y-auto rounded-md bg-stone-50 p-3">
              <OutlineTree items={project.paper_outline || []} />
            </div>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-stone-600">具体要求</h3>
              {project.specific_requirements ? (
                <button
                  type="button"
                  className="btn-outline text-xs"
                  onClick={() =>
                    setFullView({
                      title: "具体要求定稿",
                      body: project.specific_requirements || "",
                    })
                  }
                >
                  查看全部
                </button>
              ) : null}
            </div>
            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-stone-50 p-3 text-xs text-stone-700">
              {project.specific_requirements
                ? project.specific_requirements.length > PREVIEW_CHARS
                  ? `${project.specific_requirements.slice(0, PREVIEW_CHARS)}…`
                  : project.specific_requirements
                : "（无）"}
            </pre>
          </div>
        </div>
      </section>
    </div>
  );
}
