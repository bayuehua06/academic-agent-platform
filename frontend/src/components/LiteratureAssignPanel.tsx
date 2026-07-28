"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, Literature, OutlineItem, Project } from "@/lib/api";
import { ZoteroBindingPanel } from "@/components/ZoteroBindingPanel";

type Chapter = {
  heading: string;
  key_points: string;
  level: number;
};

type Props = {
  projectId: string;
  project: Project;
  literatures: Literature[];
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
  onReload: () => Promise<void>;
};

type FilterMode = "all" | "unassigned" | "chapter" | "other";

function buildChapters(outline: OutlineItem[] | null | undefined): Chapter[] {
  if (!outline?.length) return [];
  const seen = new Set<string>();
  const list: Chapter[] = [];
  for (const item of outline) {
    const heading = (item.heading || "").trim();
    if (!heading || seen.has(heading)) continue;
    seen.add(heading);
    list.push({
      heading,
      key_points: (item.key_points || "").trim(),
      level: item.level || 1,
    });
  }
  return list;
}

function skippedStorageKey(projectId: string): string {
  return `lit-assign-skipped:${projectId}`;
}

function loadSkippedHeadings(projectId: string): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(skippedStorageKey(projectId));
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((x): x is string => typeof x === "string" && x.trim()));
  } catch {
    return new Set();
  }
}

function persistSkippedHeadings(projectId: string, headings: Set<string>) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    skippedStorageKey(projectId),
    JSON.stringify(Array.from(headings)),
  );
}

export function LiteratureAssignPanel({
  projectId,
  project,
  literatures,
  busy,
  setBusy,
  onMessage,
  onError,
  onReload,
}: Props) {
  const chapters = useMemo(
    () => buildChapters(project.paper_outline),
    [project.paper_outline],
  );
  const outlineReady = Boolean(project.outline_ready && chapters.length);
  const zoteroBound = Boolean(
    project.zotero_collection_id && project.zotero_binding_mode,
  );

  const [step, setStep] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [saving, setSaving] = useState(false);
  const [skippedHeadings, setSkippedHeadings] = useState<Set<string>>(() =>
    loadSkippedHeadings(projectId),
  );

  const current = chapters[step] || null;
  const heading = current?.heading || "";

  const assignedByHeading = useMemo(() => {
    const map = new Map<string, number>();
    for (const lit of literatures) {
      for (const h of lit.assigned_headings || []) {
        map.set(h, (map.get(h) || 0) + 1);
      }
    }
    return map;
  }, [literatures]);

  const unassignedCount = useMemo(
    () => literatures.filter((l) => !(l.assigned_headings || []).length).length,
    [literatures],
  );

  const chapterSelectedIds = useMemo(() => {
    const set = new Set<string>();
    for (const lit of literatures) {
      if ((lit.assigned_headings || []).includes(heading)) set.add(lit.id);
    }
    return set;
  }, [literatures, heading]);

  const withAssignCount = chapters.filter(
    (c) => (assignedByHeading.get(c.heading) || 0) > 0,
  ).length;
  const skippedCount = chapters.filter(
    (c) =>
      skippedHeadings.has(c.heading) && !(assignedByHeading.get(c.heading) || 0),
  ).length;
  const reviewedCount = withAssignCount + skippedCount;
  const wizardDone = chapters.length > 0 && reviewedCount >= chapters.length;

  useEffect(() => {
    if (step >= chapters.length && chapters.length) setStep(0);
  }, [chapters.length, step]);

  useEffect(() => {
    setQuery("");
    setFilter("all");
  }, [heading]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return literatures.filter((lit) => {
      const heads = lit.assigned_headings || [];
      if (filter === "unassigned" && heads.length) return false;
      if (filter === "chapter" && !heads.includes(heading)) return false;
      if (filter === "other" && (heads.includes(heading) || !heads.length)) return false;
      if (!q) return true;
      const blob = [
        lit.title,
        ...(lit.authors || []),
        lit.doi || "",
        lit.collection_path || "",
        ...(lit.assigned_headings || []),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [literatures, query, filter, heading]);

  async function syncFromZotero() {
    setBusy(true);
    onError("");
    onMessage("正在从 Zotero 重新同步（保留已有章节分配）…");
    try {
      const rows = await apiFetch<Literature[]>(
        `/zotero/projects/${projectId}/sync`,
        { method: "POST" },
      );
      onMessage(`已同步 ${rows.length} 篇；仍存在的条目上章节分配已保留`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "同步失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveChapterSelection(nextIds: Set<string>) {
    if (!heading) return;
    setSaving(true);
    setBusy(true);
    onError("");
    try {
      await apiFetch(`/projects/${projectId}/literature-assignments/${encodeURIComponent(heading)}`, {
        method: "PUT",
        body: JSON.stringify({ literature_ids: Array.from(nextIds) }),
      });
      if (nextIds.size > 0) {
        setSkippedHeadings((prev) => {
          if (!prev.has(heading)) return prev;
          const next = new Set(prev);
          next.delete(heading);
          persistSkippedHeadings(projectId, next);
          return next;
        });
      }
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "保存分配失败");
    } finally {
      setSaving(false);
      setBusy(false);
    }
  }

  async function toggleLit(id: string) {
    const next = new Set(chapterSelectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    await saveChapterSelection(next);
  }

  async function skipChapter() {
    if (!heading) return;
    setSkippedHeadings((prev) => {
      const next = new Set(prev);
      next.add(heading);
      persistSkippedHeadings(projectId, next);
      return next;
    });
    if (chapterSelectedIds.size) {
      await saveChapterSelection(new Set());
    }
    onMessage(
      chapterSelectedIds.size
        ? `已清空并跳过「${heading}」`
        : `已跳过「${heading}」（本章不指定文献）`,
    );
    if (step < chapters.length - 1) setStep((s) => s + 1);
  }

  return (
    <div className="space-y-6">
      <ZoteroBindingPanel
        projectId={projectId}
        project={project}
        busy={busy}
        setBusy={setBusy}
        onMessage={onMessage}
        onError={onError}
        onReload={onReload}
      />

      {!zoteroBound && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          请先完成上方 Zotero 绑定（挂接已有集合），再按章分配文献。
        </p>
      )}

      <section className="card space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold">按章分配文献</h2>
            <p className="mt-1 text-sm text-stone-500">
              Attach 模式：文献以 Zotero 为真源。请从已同步文献中为每章勾选必用文献；不检索、不向 Zotero 写入。
            </p>
          </div>
          {outlineReady && (
            <p className="text-sm text-stone-600">
              进度{" "}
              <span className="font-medium text-brand-700">
                {reviewedCount}/{chapters.length}
              </span>{" "}
              章
              <span className="text-stone-400">
                （已分配 {withAssignCount} · 跳过 {skippedCount}）
              </span>
            </p>
          )}
        </div>

        <p className="text-sm text-stone-600">
          已同步 {literatures.length} 篇；未分配到任何章{" "}
          <span className="font-medium text-amber-800">{unassignedCount}</span> 篇
          （Writer 将忽略未分配文献）。
        </p>

        {!outlineReady && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
            请先在「Inputs」锁定大纲后再分配。
          </p>
        )}

        {outlineReady && wizardDone && (
          <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            向导已走完。可到「Draft」跑 Agent（仅使用各章已分配文献）。
          </p>
        )}

        {outlineReady && (
          <ol className="flex flex-wrap gap-2">
            {chapters.map((ch, idx) => {
              const count = assignedByHeading.get(ch.heading) || 0;
              const active = idx === step;
              const done = count > 0;
              const skipped = !done && skippedHeadings.has(ch.heading);
              return (
                <li key={ch.heading}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setStep(idx)}
                    className={`rounded-md border px-2.5 py-1.5 text-left text-xs transition ${
                      active
                        ? "border-brand-600 bg-brand-50 text-brand-800"
                        : done
                          ? "border-stone-300 bg-stone-50 text-stone-700 hover:border-brand-400"
                          : skipped
                            ? "border-dashed border-stone-300 bg-stone-50 text-stone-500"
                            : "border-stone-200 text-stone-500 hover:border-stone-400"
                    }`}
                  >
                    <span className="font-medium">
                      {done ? "✓ " : skipped ? "– " : ""}
                      {idx + 1}. {ch.heading}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-stone-500">
                      {done ? `${count} 篇` : skipped ? "已跳过" : "未分配"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {zoteroBound && current && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-display text-base font-semibold">
              第 {step + 1}/{chapters.length} 章 · {current.heading}
              <span className="ml-2 text-sm font-normal text-stone-500">
                已选 {chapterSelectedIds.size} 篇
              </span>
            </h3>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy || step <= 0}
                onClick={() => setStep((s) => Math.max(0, s - 1))}
              >
                上一章
              </button>
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy || step >= chapters.length - 1}
                onClick={() => setStep((s) => Math.min(chapters.length - 1, s + 1))}
              >
                下一章
              </button>
              <button
                type="button"
                className="btn-outline"
                disabled={busy}
                onClick={syncFromZotero}
              >
                从 Zotero 同步
              </button>
              <button
                type="button"
                className="btn-outline"
                disabled={busy || saving || !heading}
                onClick={() => void skipChapter()}
              >
                本章不指定文献
              </button>
            </div>
          </div>

          {current.key_points ? (
            <p className="text-sm text-stone-500 whitespace-pre-wrap">{current.key_points}</p>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <input
              className="input min-w-[16rem] flex-1"
              placeholder="搜索标题 / 作者 / DOI / 路径…"
              value={query}
              disabled={busy}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="input w-auto"
              value={filter}
              disabled={busy}
              onChange={(e) => setFilter(e.target.value as FilterMode)}
            >
              <option value="all">全部</option>
              <option value="unassigned">仅未分配任何章</option>
              <option value="chapter">仅本章已选</option>
              <option value="other">仅其它章已选</option>
            </select>
          </div>

          {!literatures.length ? (
            <p className="text-sm text-stone-500">
              尚无同步文献。请点「从 Zotero 同步」，或确认绑定集合内确有条目。
            </p>
          ) : !filtered.length ? (
            <p className="text-sm text-stone-500">无匹配文献，试试清空搜索或换 filter。</p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {filtered.map((lit) => {
                const checked = chapterSelectedIds.has(lit.id);
                const heads = lit.assigned_headings || [];
                return (
                  <li key={lit.id} className="flex gap-3 py-3">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={checked}
                      disabled={busy || saving}
                      onChange={() => void toggleLit(lit.id)}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="font-medium leading-snug text-ink">{lit.title}</p>
                      <p className="mt-0.5 text-xs text-stone-500">
                        {(lit.authors || []).slice(0, 3).join(", ")}
                        {lit.year ? ` · ${lit.year}` : ""}
                        {lit.collection_path ? ` · ${lit.collection_path}` : ""}
                      </p>
                      <p className="mt-0.5 text-[11px] text-stone-500">
                        证据 {lit.evidence_tier || "metadata_only"}
                        {lit.evidence_source ? ` · ${lit.evidence_source}` : ""}
                        {!lit.abstract ? " · 缺摘要/证据文本" : ""}
                      </p>
                      {heads.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {heads.map((h) => (
                            <span
                              key={h}
                              className={`rounded px-1.5 py-0.5 text-[11px] ${
                                h === heading
                                  ? "bg-brand-100 text-brand-800"
                                  : "bg-stone-100 text-stone-600"
                              }`}
                            >
                              {h}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
