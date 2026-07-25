"use client";

import { DraftVersion } from "@/lib/api";

type Props = {
  draft?: DraftVersion | null;
};

export function DraftViewer({ draft }: Props) {
  if (!draft) {
    return (
      <div className="rounded-lg border border-dashed border-stone-300 p-8 text-center text-sm text-stone-500">
        选择版本或运行 Agent 生成草稿
      </div>
    );
  }

  const full = [
    draft.content_markdown,
    draft.apa_references_block
      ? `\n\n## References\n\n${draft.apa_references_block}`
      : "",
  ].join("");

  return (
    <article className="prose-academic max-h-[70vh] overflow-y-auto rounded-lg border border-stone-200 bg-white p-6">
      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">
        {full}
      </pre>
    </article>
  );
}
