"use client";

import { Literature } from "@/lib/api";
import { formatDate } from "@/lib/utils";

type Props = {
  items: Literature[];
  onToggle?: (id: string, selected: boolean) => void;
};

export function ZoteroList({ items, onToggle }: Props) {
  if (!items.length) {
    return (
      <p className="text-sm text-stone-500">
        暂无已确认文献。请先检索并勾选入库。
      </p>
    );
  }

  return (
    <ul className="space-y-4">
      {items.map((lit) => (
        <li
          key={lit.id}
          className="border-b border-stone-200 pb-4 last:border-0"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <h3 className="font-medium text-ink leading-snug">{lit.title}</h3>
              <p className="mt-1 text-sm text-stone-600">
                {(lit.authors || []).join(", ") || "Unknown"} · {lit.year || "n.d."}
                {lit.relevance_score != null && (
                  <span className="ml-2 text-brand-500">
                    相关度 {lit.relevance_score.toFixed(2)}
                  </span>
                )}
              </p>
              {lit.doi && (
                <a
                  href={`https://doi.org/${lit.doi}`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-sm text-brand-600 underline"
                >
                  DOI: {lit.doi}
                </a>
              )}
              {(lit.evidence_tier || lit.evidence_source) && (
                <p className="mt-1 text-xs text-stone-500">
                  证据层级 {lit.evidence_tier || "metadata_only"}
                  {lit.evidence_source ? ` · ${lit.evidence_source}` : ""}
                </p>
              )}
              {!lit.abstract && (
                <p className="mt-1 text-xs text-amber-700">
                  缺少摘要/证据文本：Writer 将降级使用，避免编造具体发现。
                </p>
              )}
              {lit.abstract && (
                <p className="mt-2 text-sm text-stone-500 line-clamp-3">{lit.abstract}</p>
              )}
              {lit.outline_heading && (
                <span className="ml-2 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600">
                  {lit.outline_heading}
                </span>
              )}
              <p className="mt-1 text-xs text-stone-400">
                Zotero key: {lit.zotero_item_key || "未同步"}
                {lit.confirmed_at ? " · 已确认" : ""} · {formatDate(lit.created_at)}
              </p>
            </div>
            {onToggle && (
              <label className="flex shrink-0 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={lit.selected_for_draft}
                  onChange={(e) => onToggle(lit.id, e.target.checked)}
                />
                用于草稿
              </label>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
