"use client";

import { DraftVersion } from "@/lib/api";

type Props = {
  draft?: DraftVersion | null;
  /** 有活动工作区时优先预览工作区正文 */
  workingMarkdown?: string | null;
};

export function DraftViewer({ draft, workingMarkdown }: Props) {
  if (workingMarkdown) {
    return (
      <article className="prose-academic max-h-[70vh] overflow-y-auto rounded-lg border border-amber-200 bg-amber-50/40 p-6">
        <p className="mb-3 text-xs font-medium text-amber-800">工作区预览（未确认）</p>
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">
          {workingMarkdown}
        </pre>
      </article>
    );
  }

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
