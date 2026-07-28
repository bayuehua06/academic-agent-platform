"use client";

import { Loader2 } from "lucide-react";

export type AgentProgress = {
  project_id: string;
  stage: string;
  label: string;
  detail?: string;
  percent?: number | null;
  updated_at?: string | null;
  running: boolean;
};

export type AgentRunResult = {
  id: string;
  project_id: string;
  version_number: number;
  major?: number | null;
  minor?: number;
  display_label: string;
  content_markdown: string;
  apa_references_block?: string | null;
  source_type: string;
  changelog?: string | null;
  created_at: string;
  verify_ok?: boolean | null;
  verification_issues?: string[];
  repair_available?: boolean;
  writer_word_count?: number | null;
  writer_word_target?: { min?: number; max?: number } | null;
  repaired?: boolean;
};

const STAGE_ORDER = [
  { id: "starting", title: "启动" },
  { id: "sync_zotero", title: "同步文献" },
  { id: "evidence", title: "构建证据" },
  { id: "drafting", title: "撰写草稿" },
  { id: "saving", title: "保存版本" },
] as const;

function stageIndex(stage: string): number {
  const idx = STAGE_ORDER.findIndex((s) => s.id === stage);
  if (idx >= 0) return idx;
  if (stage === "done") return STAGE_ORDER.length;
  return 0;
}

type Props = {
  open: boolean;
  progress: AgentProgress | null;
  elapsedSec: number;
  /** 校验失败、等待用户决定是否 repair */
  repairPrompt?: AgentRunResult | null;
  repairing?: boolean;
  onConfirmRepair?: () => void;
  onSkipRepair?: () => void;
};

export function AgentRunOverlay({
  open,
  progress,
  elapsedSec,
  repairPrompt = null,
  repairing = false,
  onConfirmRepair,
  onSkipRepair,
}: Props) {
  if (!open) return null;

  const awaiting = Boolean(repairPrompt && !repairing);
  const current = progress?.stage || (awaiting ? "saving" : "starting");
  const idx = stageIndex(current);
  const label = repairing
    ? "正在自动补写 / 压缩…"
    : awaiting
      ? "校验未通过，请确认是否继续自动修复"
      : progress?.label || "正在运行学术 Agent…";
  const detail = repairing
    ? "将基于当前草稿做一轮 repair；结构会再次硬锁回大纲。"
    : awaiting
      ? "选「否」将保留当前草稿，便于你在精修里手动调整。"
      : progress?.detail || "首次构建证据可能较慢（抓取摘要 / PDF）。";
  const percent = repairing
    ? 70
    : awaiting
      ? 100
      : typeof progress?.percent === "number"
        ? Math.max(0, Math.min(100, progress.percent))
        : Math.min(90, 8 + idx * 18);

  const mins = Math.floor(elapsedSec / 60);
  const secs = elapsedSec % 60;
  const clock = mins > 0 ? `${mins}:${String(secs).padStart(2, "0")}` : `${secs}s`;

  const issues = repairPrompt?.verification_issues || [];
  const words = repairPrompt?.writer_word_count;
  const target = repairPrompt?.writer_word_target;

  return (
    <div
      className="fixed bottom-4 right-4 z-[60] w-[min(100vw-2rem,24rem)] rounded-xl border border-stone-200 bg-white p-4 shadow-lg"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        {!awaiting ? (
          <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-brand-600" />
        ) : (
          <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-xs font-bold text-amber-800">
            !
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">
            {awaiting ? "学术 Agent · 校验结果" : "学术 Agent 运行中"}
          </p>
          <p className="mt-0.5 text-sm text-stone-700">{label}</p>
          {detail ? <p className="mt-1 text-xs text-stone-500">{detail}</p> : null}
          {!awaiting ? (
            <p className="mt-2 text-xs text-stone-400">已用时 {clock}</p>
          ) : (
            <p className="mt-2 text-xs text-stone-400">
              已生成 v{repairPrompt?.display_label || repairPrompt?.version_number}
              {typeof words === "number" ? ` · 约 ${words} 词` : ""}
              {target?.min != null && target?.max != null
                ? ` · 目标 ${target.min}-${target.max}`
                : ""}
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-stone-100">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            awaiting ? "bg-amber-500" : "bg-brand-500"
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>

      {awaiting && issues.length > 0 && (
        <div className="mt-3 max-h-40 overflow-auto rounded-md border border-amber-100 bg-amber-50 px-2.5 py-2">
          <p className="text-[11px] font-medium text-amber-900">verify_ok=False 原因</p>
          <ul className="mt-1 space-y-1">
            {issues.map((issue) => (
              <li key={issue} className="text-[11px] leading-snug text-amber-900/90">
                · {issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {awaiting ? (
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className="btn-outline text-xs"
            onClick={onSkipRepair}
          >
            否，先精修
          </button>
          <button type="button" className="btn text-xs" onClick={onConfirmRepair}>
            是，继续自动修复
          </button>
        </div>
      ) : (
        <ol className="mt-3 space-y-1.5">
          {STAGE_ORDER.map((s, i) => {
            const done = i < idx || current === "done";
            const active = i === idx && current !== "done" && current !== "error";
            return (
              <li
                key={s.id}
                className={`flex items-center gap-2 text-xs ${
                  active
                    ? "font-medium text-brand-700"
                    : done
                      ? "text-stone-500"
                      : "text-stone-300"
                }`}
              >
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    active ? "bg-brand-600" : done ? "bg-stone-400" : "bg-stone-200"
                  }`}
                />
                {s.title}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
