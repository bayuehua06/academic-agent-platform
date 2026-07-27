"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export type SectionDirective = {
  id: string;
  project_id: string;
  outline_heading: string;
  directive_text: string;
  instruction?: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
};

type Props = {
  projectId: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (m: string) => void;
  onError: (e: string) => void;
  refreshKey?: string | number;
};

export function SectionDirectivesPanel({
  projectId,
  busy,
  setBusy,
  onMessage,
  onError,
  refreshKey,
}: Props) {
  const [rows, setRows] = useState<SectionDirective[]>([]);

  const load = useCallback(() => {
    apiFetch<SectionDirective[]>(`/projects/${projectId}/section-directives`)
      .then(setRows)
      .catch(() => setRows([]));
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function deactivate(id: string) {
    if (!confirm("停用该章节指令？整篇重生时将不再注入。")) return;
    setBusy(true);
    onError("");
    try {
      await apiFetch(`/projects/${projectId}/section-directives/${id}`, {
        method: "DELETE",
      });
      onMessage("已停用章节指令");
      load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "停用失败");
    } finally {
      setBusy(false);
    }
  }

  if (!rows.length) {
    return (
      <div className="card py-3">
        <h3 className="font-display text-sm font-semibold">已落库章节指令</h3>
        <p className="mt-1 text-xs text-stone-500">
          确认精修工作区后，各节精修指令会保存在此；整篇 run-agent 时按节注入。
        </p>
      </div>
    );
  }

  return (
    <div className="card space-y-2 py-3">
      <h3 className="font-display text-sm font-semibold">
        已落库章节指令（{rows.length}）
      </h3>
      <ul className="max-h-48 space-y-2 overflow-y-auto">
        {rows.map((r) => (
          <li
            key={r.id}
            className="rounded border border-stone-200 bg-stone-50/80 px-2 py-1.5 text-xs"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium text-stone-800">{r.outline_heading}</span>
              <button
                type="button"
                className="shrink-0 text-[10px] text-red-600 hover:underline"
                disabled={busy}
                onClick={() => deactivate(r.id)}
              >
                停用
              </button>
            </div>
            <p className="mt-0.5 whitespace-pre-wrap text-stone-600">
              {r.instruction || r.directive_text}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
