"use client";

import { useEffect, useState } from "react";
import { DraftVersion } from "@/lib/api";
import { formatDate } from "@/lib/utils";

type Props = {
  versions: DraftVersion[];
  selectedId?: string;
  onSelect: (v: DraftVersion) => void;
};

export function VersionHistory({ versions, selectedId, onSelect }: Props) {
  const [detail, setDetail] = useState<DraftVersion | null>(null);

  useEffect(() => {
    if (!detail) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDetail(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detail]);

  if (!versions.length) {
    return <p className="text-sm text-stone-500">尚无版本记录。</p>;
  }

  return (
    <>
      <ul className="space-y-2">
        {versions.map((v) => (
          <li key={v.id}>
            <div
              className={`rounded-md border px-3 py-2 text-sm transition ${
                selectedId === v.id
                  ? "border-brand-500 bg-brand-50"
                  : "border-stone-200 hover:border-stone-300"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(v)}
                className="w-full text-left"
              >
                <div className="flex justify-between gap-2">
                  <span className="font-medium">
                    v{v.display_label || v.version_number}
                  </span>
                  <span className="text-xs text-stone-500">{v.source_type}</span>
                </div>
                <p className="mt-0.5 text-xs text-stone-500">
                  {formatDate(v.created_at)}
                </p>
                {v.changelog && (
                  <p className="mt-1 line-clamp-2 text-xs text-stone-400">
                    {v.changelog}
                  </p>
                )}
              </button>
              {v.changelog && (
                <div className="mt-1.5 flex justify-end">
                  <button
                    type="button"
                    className="text-xs text-brand-600 underline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDetail(v);
                    }}
                  >
                    查看完整 changelog
                  </button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>

      {detail && (
        <div
          className="fixed inset-0 z-[70] flex items-end justify-center bg-black/40 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="changelog-detail-title"
          onClick={() => setDetail(null)}
        >
          <div
            className="max-h-[80vh] w-full max-w-lg overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 border-b border-stone-100 px-4 py-3">
              <div>
                <h3
                  id="changelog-detail-title"
                  className="text-sm font-medium text-ink"
                >
                  v{detail.display_label || detail.version_number} changelog
                </h3>
                <p className="mt-0.5 text-xs text-stone-500">
                  {detail.source_type} · {formatDate(detail.created_at)}
                </p>
              </div>
              <button
                type="button"
                className="btn-outline text-xs"
                onClick={() => setDetail(null)}
              >
                关闭
              </button>
            </div>
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words px-4 py-3 text-xs leading-relaxed text-stone-700">
              {detail.changelog}
            </pre>
          </div>
        </div>
      )}
    </>
  );
}
