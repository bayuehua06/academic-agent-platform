"use client";

import { useEffect, useMemo, useState } from "react";
import { Lock, Sparkles } from "lucide-react";
import { apiFetch, DraftWorking, Literature } from "@/lib/api";

type SectionMeta = {
  heading: string;
  level: number;
  status: string;
  similarity: number;
  has_locked_blocks: boolean;
  locked_count: number;
  polished: boolean;
};

type LineRow = { type: string; text: string };

type Candidate = {
  markdown: string;
  instruction: string;
};

type Props = {
  projectId: string;
  working: DraftWorking;
  literatures: Literature[];
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (m: string) => void;
  onError: (e: string) => void;
  onWorkingChange: (w: DraftWorking) => void;
};

const STATUS_STYLE: Record<string, string> = {
  unchanged: "bg-stone-100 text-stone-600",
  modified: "bg-amber-100 text-amber-800",
  added: "bg-emerald-100 text-emerald-800",
  polished: "bg-sky-100 text-sky-800",
  removed: "bg-red-100 text-red-700",
};

const MAX_CANDIDATES = 5;

type ViewTab = "diff" | "edit";

export function DraftPolishPanel({
  projectId,
  working,
  literatures,
  busy,
  setBusy,
  onMessage,
  onError,
  onWorkingChange,
}: Props) {
  const sections = (working.sections || []) as SectionMeta[];
  const staleSet = useMemo(
    () => new Set((working.stale_headings || []).map((h) => h.toLowerCase())),
    [working.stale_headings],
  );

  const [selected, setSelected] = useState<string>("");
  const [viewTab, setViewTab] = useState<ViewTab>("diff");
  const [instruction, setInstruction] = useState("");
  const [selectedLitIds, setSelectedLitIds] = useState<string[]>([]);
  const [lineDiff, setLineDiff] = useState<LineRow[]>([]);
  const [editText, setEditText] = useState("");
  const [editBaseline, setEditBaseline] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [previewDiff, setPreviewDiff] = useState<LineRow[]>([]);
  const [polishMeta, setPolishMeta] = useState<{ mode?: string; model?: string | null }>({});
  const [outlineKeyPoints, setOutlineKeyPoints] = useState("");
  const [factsDraft, setFactsDraft] = useState(working.working_facts || "");

  const preview = candidates.length ? candidates[candidates.length - 1].markdown : null;
  const editDirty = editText !== editBaseline;
  const factsDirty = (factsDraft || "") !== (working.working_facts || "");

  useEffect(() => {
    setFactsDraft(working.working_facts || "");
  }, [working.working_facts, working.updated_at]);

  useEffect(() => {
    if (!selected && sections.length) {
      setSelected(sections[0].heading);
    }
  }, [sections, selected]);

  useEffect(() => {
    if (!selected) return;
    setCandidates([]);
    setPreviewDiff([]);
    setPolishMeta({});
    apiFetch<{
      lines: LineRow[];
      working_markdown?: string;
      base_markdown?: string;
      outline_key_points?: string;
    }>(
      `/drafts/${projectId}/working/section-diff?heading=${encodeURIComponent(selected)}`,
    )
      .then((r) => {
        setLineDiff(r.lines || []);
        const md = r.working_markdown || "";
        setEditText(md);
        setEditBaseline(md);
        const fromDiff = (r.outline_key_points || "").trim();
        const fromSeeds = (working.outline_seeds?.[selected] || "").trim();
        setOutlineKeyPoints(fromDiff || fromSeeds);
      })
      .catch(() => {
        setLineDiff([]);
        setEditText("");
        setEditBaseline("");
        setOutlineKeyPoints((working.outline_seeds?.[selected] || "").trim());
      });
  }, [projectId, selected, working.updated_at, working.outline_seeds]);

  const current = useMemo(
    () => sections.find((s) => s.heading === selected),
    [sections, selected],
  );

  async function saveFacts() {
    setBusy(true);
    onError("");
    try {
      const wrk = await apiFetch<DraftWorking>(`/drafts/${projectId}/working/facts`, {
        method: "PATCH",
        body: JSON.stringify({ working_facts: factsDraft }),
      });
      onWorkingChange(wrk);
      onMessage("已保存 Working Facts");
    } catch (err) {
      onError(err instanceof Error ? err.message : "保存 Facts 失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveManualEdit() {
    if (!selected || !editText.trim()) {
      onError("编辑内容为空");
      return;
    }
    setBusy(true);
    onError("");
    try {
      const wrk = await apiFetch<DraftWorking>(
        `/drafts/${projectId}/working/accept-section`,
        {
          method: "POST",
          body: JSON.stringify({
            heading: selected,
            preview_markdown: editText.trim(),
            instruction: "[manual edit] User edited section in workspace editor.",
          }),
        },
      );
      onWorkingChange(wrk);
      setEditBaseline(editText.trim());
      setCandidates([]);
      onMessage(`已将「${selected}」手改写入工作区`);
      setViewTab("diff");
    } catch (err) {
      onError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function runPolish(fromPreview: boolean) {
    if (!selected || !instruction.trim()) {
      onError("请选择章节并填写精修指令");
      return;
    }
    if (fromPreview && !preview) {
      onError("尚无预览可继续");
      return;
    }
    setBusy(true);
    onError("");
    try {
      const body: Record<string, unknown> = {
        heading: selected,
        instruction: instruction.trim(),
        literature_ids: selectedLitIds.length ? selectedLitIds : null,
      };
      if (fromPreview && preview) {
        body.base_markdown = preview;
        body.prior_instructions = candidates.map((c) => c.instruction);
      } else if (editDirty && editText.trim()) {
        body.section_markdown = editText.trim();
      }
      const res = await apiFetch<{
        preview_markdown: string;
        mode: string;
        model?: string | null;
        line_diff?: LineRow[];
        locked_count?: number;
      }>(`/drafts/${projectId}/working/polish-section`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setCandidates((prev) => {
        const next = fromPreview ? prev : [];
        return [
          ...next.slice(-(MAX_CANDIDATES - 1)),
          { markdown: res.preview_markdown, instruction: instruction.trim() },
        ];
      });
      setPreviewDiff(res.line_diff || []);
      setPolishMeta({ mode: res.mode, model: res.model });
      const turnHint = fromPreview
        ? ` · 第 ${(candidates.length || 0) + 1} 轮（基于预览）`
        : editDirty
          ? " · 基于编辑区草稿"
          : "";
      onMessage(
        res.mode === "llm"
          ? `已生成预览（${res.model || "llm"}${turnHint}）`
          : "无 Key / 调用失败：返回原文预览，可仍手动采纳或检查 Key",
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : "精修失败");
    } finally {
      setBusy(false);
    }
  }

  async function acceptPreview() {
    if (!preview || !selected) return;
    setBusy(true);
    onError("");
    try {
      const wrk = await apiFetch<DraftWorking>(
        `/drafts/${projectId}/working/accept-section`,
        {
          method: "POST",
          body: JSON.stringify({
            heading: selected,
            preview_markdown: preview,
            instruction:
              candidates.map((c) => c.instruction).filter(Boolean).join(" → ") ||
              instruction.trim(),
          }),
        },
      );
      onWorkingChange(wrk);
      setCandidates([]);
      setPreviewDiff([]);
      setEditText(preview);
      setEditBaseline(preview);
      onMessage(
        `已采纳「${selected}」精修（下游已标「建议再精修」；指令已暂存）`,
      );
      setViewTab("diff");
    } catch (err) {
      onError(err instanceof Error ? err.message : "采纳失败");
    } finally {
      setBusy(false);
    }
  }

  const citedInSectionIds = useMemo(() => {
    const text = `${editText}\n${preview || ""}`.toLowerCase();
    if (!text.trim()) return new Set<string>();
    const ids = new Set<string>();
    for (const lit of literatures) {
      const year = (lit.year || "").trim();
      if (year && !text.includes(year.toLowerCase())) continue;
      const authors = lit.authors || [];
      const surnames = authors
        .map((a) => {
          const s = String(a).trim();
          if (!s) return "";
          if (s.includes(",")) return s.split(",")[0].trim().toLowerCase();
          const parts = s.split(/\s+/);
          return (parts[parts.length - 1] || "").toLowerCase();
        })
        .filter((x) => x.length >= 2);
      if (surnames.some((sn) => text.includes(sn))) {
        ids.add(lit.id);
      }
    }
    return ids;
  }, [editText, preview, literatures]);

  function toggleLit(id: string) {
    setSelectedLitIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function selectSection(heading: string) {
    if (editDirty && !confirm("编辑区有未保存修改，切换章节将丢弃。继续？")) {
      return;
    }
    if (candidates.length && !confirm("当前节有未采纳的预览候选，切换将丢弃。继续？")) {
      return;
    }
    setSelected(heading);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
      <aside className="card space-y-2 py-3">
        <h3 className="font-display text-sm font-semibold">章节（相对 base）</h3>
        <ul className="max-h-[50vh] space-y-1 overflow-y-auto">
          {sections.map((s) => {
            const stale = staleSet.has(s.heading.toLowerCase());
            return (
              <li key={s.heading}>
                <button
                  type="button"
                  onClick={() => selectSection(s.heading)}
                  className={`flex w-full items-start gap-1 rounded-md border px-2 py-1.5 text-left text-xs transition ${
                    selected === s.heading
                      ? "border-brand-500 bg-brand-50"
                      : "border-stone-200 hover:border-stone-300"
                  }`}
                >
                  <span className="min-w-0 flex-1 font-medium leading-snug">
                    {s.heading}
                    {stale && (
                      <span className="mt-0.5 block text-[10px] font-normal text-amber-700">
                        建议再精修
                      </span>
                    )}
                  </span>
                  {s.has_locked_blocks && (
                    <Lock
                      className="mt-0.5 h-3 w-3 shrink-0 text-stone-400"
                      aria-label="含图/表锁定"
                    />
                  )}
                  <span
                    className={`shrink-0 rounded px-1 py-0.5 text-[10px] ${STATUS_STYLE[s.status] || STATUS_STYLE.unchanged}`}
                  >
                    {s.status}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <div className="space-y-4">
        <div className="card space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-base font-semibold">{selected || "选择章节"}</h3>
            {current?.has_locked_blocks && (
              <span className="inline-flex items-center gap-1 rounded bg-stone-100 px-2 py-0.5 text-xs text-stone-600">
                <Lock className="h-3 w-3" />
                {current.locked_count} 个图/表块已锁定
              </span>
            )}
            {staleSet.has((selected || "").toLowerCase()) && (
              <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] text-amber-800">
                上游已变 · 建议再精修
              </span>
            )}
            {editDirty && (
              <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] text-amber-800">
                编辑未保存
              </span>
            )}
            {candidates.length > 0 && (
              <span className="rounded bg-sky-100 px-2 py-0.5 text-[10px] text-sky-800">
                候选轮次 {candidates.length}/{MAX_CANDIDATES}
              </span>
            )}
          </div>

          {outlineKeyPoints ? (
            <div className="rounded-md border border-violet-200 bg-violet-50/60 px-3 py-2 text-xs text-violet-900">
              <p className="mb-1 font-medium">大纲 Seed（硬输入）</p>
              <p className="whitespace-pre-wrap leading-relaxed text-violet-800/90">
                {outlineKeyPoints}
              </p>
            </div>
          ) : null}

          <label className="block text-xs text-stone-600">
            Working Facts（跨节硬约束：已定 case / 主张 / 专有名）
            <textarea
              className="input mt-1 min-h-[64px]"
              value={factsDraft}
              disabled={busy}
              onChange={(e) => setFactsDraft(e.target.value)}
              placeholder="例如：Case = Acme Corp，四提案名为 A/B/C/D；第1章已改 case 为…"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-outline text-xs"
              disabled={busy || !factsDirty}
              onClick={() => saveFacts()}
            >
              保存 Facts
            </button>
          </div>

          <label className="block text-xs text-stone-600">
            精修指令（会暂存为章节 directive）
            <textarea
              className="input mt-1 min-h-[72px]"
              value={instruction}
              disabled={busy || !selected}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="例如：在我改过的基础上加强批判性讨论；补充对 Kim et al. 的引用"
            />
          </label>

          {literatures.length > 0 && (
            <div>
              <p className="mb-1 text-xs text-stone-600">
                本次必须考虑的文献（可选；默认全库）
                <span className="ml-2 text-stone-400">
                  紫边=本节已出现引用 · 蓝底=本次勾选 · 悬停看详情
                </span>
              </p>
              <div className="flex max-h-36 flex-wrap content-start gap-1.5 overflow-y-auto p-1">
                {literatures.slice(0, 40).map((lit) => {
                  const picked = selectedLitIds.includes(lit.id);
                  const inSection = citedInSectionIds.has(lit.id);
                  return (
                    <LitChip
                      key={lit.id}
                      lit={lit}
                      picked={picked}
                      inSection={inSection}
                      disabled={busy}
                      onToggle={() => toggleLit(lit.id)}
                    />
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn gap-1.5 text-xs"
              disabled={busy || !selected || !instruction.trim()}
              onClick={() => runPolish(false)}
            >
              <Sparkles className="h-3.5 w-3.5" />
              {preview ? "重新精修（从工作区）" : "生成精修预览"}
              {!preview && editDirty ? "（含编辑区）" : ""}
            </button>
            {preview && (
              <>
                <button
                  type="button"
                  className="btn gap-1.5 text-xs"
                  disabled={busy || !instruction.trim()}
                  onClick={() => runPolish(true)}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  基于预览继续精修
                </button>
                <button
                  type="button"
                  className="btn text-xs"
                  disabled={busy}
                  onClick={() => acceptPreview()}
                >
                  采纳当前预览
                </button>
                {candidates.length > 1 && (
                  <button
                    type="button"
                    className="btn-outline text-xs"
                    disabled={busy}
                    onClick={() => {
                      setCandidates((prev) => prev.slice(0, -1));
                      setPreviewDiff([]);
                      onMessage("已回退到上一候选");
                    }}
                  >
                    回退上一候选
                  </button>
                )}
                <button
                  type="button"
                  className="btn-outline text-xs"
                  disabled={busy}
                  onClick={() => {
                    setCandidates([]);
                    setPreviewDiff([]);
                  }}
                >
                  放弃全部预览
                </button>
                {polishMeta.mode && (
                  <span className="self-center text-xs text-stone-500">
                    mode={polishMeta.mode}
                    {polishMeta.model ? ` · ${polishMeta.model}` : ""}
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        <div className="card space-y-3 py-3">
          <div className="flex flex-wrap items-center gap-1 border-b border-stone-100 pb-2">
            <TabBtn active={viewTab === "diff"} onClick={() => setViewTab("diff")}>
              对比 base
            </TabBtn>
            <TabBtn active={viewTab === "edit"} onClick={() => setViewTab("edit")}>
              手工编辑
            </TabBtn>
          </div>

          {viewTab === "diff" && (
            <div className={`grid gap-4 ${preview ? "lg:grid-cols-2" : ""}`}>
              <DiffBox title="相对 base 的变化" rows={lineDiff} />
              {preview && <DiffBox title="预览 vs 上一底稿" rows={previewDiff} tone="sky" />}
            </div>
          )}

          {viewTab === "edit" && (
            <div className="space-y-2">
              <p className="text-xs text-stone-500">
                直接改本节 Markdown。可先「写入工作区」，或带着未保存改动点「生成精修预览」让模型在你改过的稿上继续改。
                图/表锁定块请尽量保留原样。
              </p>
              <textarea
                className="input min-h-[280px] font-mono text-xs leading-relaxed"
                value={editText}
                disabled={busy || !selected}
                onChange={(e) => setEditText(e.target.value)}
                spellCheck={false}
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn text-xs"
                  disabled={busy || !selected || !editDirty}
                  onClick={() => saveManualEdit()}
                >
                  写入工作区
                </button>
                <button
                  type="button"
                  className="btn-outline text-xs"
                  disabled={busy || !editDirty}
                  onClick={() => setEditText(editBaseline)}
                >
                  还原
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LitChip({
  lit,
  picked,
  inSection,
  disabled,
  onToggle,
}: {
  lit: Literature;
  picked: boolean;
  inSection: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  const label = `${(lit.authors?.[0] || "Anon").toString().slice(0, 22)} ${lit.year || ""}`.trim();
  const authorsFull = (lit.authors || []).join("; ") || "—";
  const abstract = (lit.abstract || "").trim();

  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        disabled={disabled}
        onClick={onToggle}
        className={`rounded border px-2 py-0.5 text-[11px] transition ${
          picked
            ? "border-brand-500 bg-brand-50 font-medium text-brand-900"
            : inSection
              ? "border-violet-400 bg-violet-50 text-violet-900"
              : "border-stone-200 text-stone-600 hover:border-stone-300"
        } ${inSection && picked ? "ring-1 ring-violet-300" : ""}`}
      >
        {inSection && <span className="mr-0.5 text-violet-500">●</span>}
        {label}
      </button>
      <span
        className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-72 rounded-md border border-stone-200 bg-white p-2 text-[11px] text-stone-700 shadow-lg group-hover:block"
        role="tooltip"
      >
        <p className="font-medium text-stone-900">{lit.title}</p>
        <p className="mt-1 text-stone-500">{authorsFull}</p>
        {lit.year && <p className="text-stone-500">{lit.year}</p>}
        {abstract && (
          <p className="mt-1 line-clamp-4 text-stone-600">{abstract}</p>
        )}
      </span>
    </span>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2.5 py-1 text-xs transition ${
        active
          ? "bg-stone-900 text-white"
          : "text-stone-600 hover:bg-stone-100"
      }`}
    >
      {children}
    </button>
  );
}

function DiffBox({
  title,
  rows,
  tone = "stone",
}: {
  title: string;
  rows: LineRow[];
  tone?: "stone" | "sky";
}) {
  const border =
    tone === "sky" ? "border-sky-200 bg-sky-50/40" : "border-stone-200 bg-stone-50/50";
  return (
    <div className={`rounded-md border ${border} p-2`}>
      <p className="mb-1 text-xs font-medium text-stone-700">{title}</p>
      <pre className="max-h-[320px] overflow-auto font-mono text-[11px] leading-relaxed">
        {rows.length === 0 ? (
          <span className="text-stone-400">（无差异）</span>
        ) : (
          rows.map((r, i) => (
            <div
              key={`${i}-${r.type}-${r.text.slice(0, 24)}`}
              className={
                r.type === "add"
                  ? "bg-emerald-100/80 text-emerald-900"
                  : r.type === "del"
                    ? "bg-red-100/70 text-red-900 line-through"
                    : "text-stone-700"
              }
            >
              {r.type === "add" ? "+ " : r.type === "del" ? "- " : "  "}
              {r.text || " "}
            </div>
          ))
        )}
      </pre>
    </div>
  );
}
