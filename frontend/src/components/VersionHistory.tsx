"use client";

import { DraftVersion } from "@/lib/api";
import { formatDate } from "@/lib/utils";

type Props = {
  versions: DraftVersion[];
  selectedId?: string;
  onSelect: (v: DraftVersion) => void;
};

export function VersionHistory({ versions, selectedId, onSelect }: Props) {
  if (!versions.length) {
    return <p className="text-sm text-stone-500">尚无版本记录。</p>;
  }

  return (
    <ul className="space-y-2">
      {versions.map((v) => (
        <li key={v.id}>
          <button
            type="button"
            onClick={() => onSelect(v)}
            className={`w-full rounded-md border px-3 py-2 text-left text-sm transition ${
              selectedId === v.id
                ? "border-brand-500 bg-brand-50"
                : "border-stone-200 hover:border-stone-300"
            }`}
          >
            <div className="flex justify-between">
              <span className="font-medium">v{v.version_number}</span>
              <span className="text-xs text-stone-500">{v.source_type}</span>
            </div>
            <p className="mt-0.5 text-xs text-stone-500">{formatDate(v.created_at)}</p>
            {v.changelog && (
              <p className="mt-1 line-clamp-2 text-xs text-stone-400">{v.changelog}</p>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
