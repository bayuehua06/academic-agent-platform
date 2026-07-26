"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiFetch,
  Literature,
  LiteratureCandidate,
  LiteratureProvider,
  LiteratureSearchRun,
  OutlineItem,
  Project,
} from "@/lib/api";
import { ZoteroList } from "@/components/ZoteroList";

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
  onToggleLit: (id: string, selected: boolean) => Promise<void>;
};

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

export function LiteratureConfirmPanel({
  projectId,
  project,
  literatures,
  busy,
  setBusy,
  onMessage,
  onError,
  onReload,
  onToggleLit,
}: Props) {
  const chapters = useMemo(
    () => buildChapters(project.paper_outline),
    [project.paper_outline],
  );

  const confirmedByHeading = useMemo(() => {
    const map = new Map<string, number>();
    for (const lit of literatures) {
      if (!lit.confirmed_at || !lit.outline_heading) continue;
      map.set(lit.outline_heading, (map.get(lit.outline_heading) || 0) + 1);
    }
    return map;
  }, [literatures]);

  const doneCount = chapters.filter((c) => (confirmedByHeading.get(c.heading) || 0) > 0).length;

  const [step, setStep] = useState(0);
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(10);
  const [run, setRun] = useState<LiteratureSearchRun | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [searching, setSearching] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [providers, setProviders] = useState<LiteratureProvider[]>([]);
  const [openaiConfigured, setOpenaiConfigured] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [autoSuggest, setAutoSuggest] = useState(false);
  const [selectedDbs, setSelectedDbs] = useState<string[]>(
    () => project.literature_databases?.length ? [...project.literature_databases] : ["ieee"],
  );
  const [savingDbs, setSavingDbs] = useState(false);

  const outlineReady = Boolean(project.outline_ready && chapters.length);
  const current = chapters[step] || null;
  const heading = current?.heading || "";

  useEffect(() => {
    const fromProject = project.literature_databases?.length
      ? [...project.literature_databases]
      : ["ieee"];
    setSelectedDbs(fromProject);
  }, [project.literature_databases]);

  useEffect(() => {
    apiFetch<{ providers: LiteratureProvider[]; openai_configured?: boolean }>(
      "/literature-providers",
    )
      .then((res) => {
        setProviders(res.providers || []);
        setOpenaiConfigured(Boolean(res.openai_configured));
      })
      .catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    if (step >= chapters.length && chapters.length) setStep(0);
  }, [chapters.length, step]);

  // 换章时清空本轮候选，避免串章
  useEffect(() => {
    setRun(null);
    setSelected(new Set());
    setQuery("");
  }, [heading]);

  async function suggestQuery(opts?: { silent?: boolean }) {
    if (!heading) return;
    const silent = Boolean(opts?.silent);
    if (!silent) {
      setSuggesting(true);
      setBusy(true);
      onError("");
      onMessage("正在生成检索词…");
    }
    try {
      const res = await apiFetch<{
        query: string;
        mode: string;
        openai_configured?: boolean;
      }>(`/projects/${projectId}/literature-search/suggest-query`, {
        method: "POST",
        body: JSON.stringify({ outline_heading: heading }),
      });
      if (res.openai_configured != null) setOpenaiConfigured(res.openai_configured);
      setQuery(res.query || "");
      if (!silent) {
        onMessage(
          res.mode === "llm"
            ? `已生成检索词（LLM）：${res.query}`
            : `已生成检索词（规则回退）：${res.query}`,
        );
      }
    } catch (err) {
      if (!silent) onError(err instanceof Error ? err.message : "生成检索词失败");
    } finally {
      if (!silent) {
        setSuggesting(false);
        setBusy(false);
      }
    }
  }

  // 可选：进章时自动填入检索词（覆盖空输入；换章后也会重新生成）
  useEffect(() => {
    if (!autoSuggest || !outlineReady || !heading) return;
    const timer = window.setTimeout(() => {
      void suggestQuery({ silent: true });
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅随章节/开关切换触发
  }, [heading, autoSuggest, outlineReady]);

  function goChapter(index: number) {
    if (index < 0 || index >= chapters.length) return;
    setStep(index);
  }

  function toggleIndex(idx: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  function selectAll(candidates: LiteratureCandidate[]) {
    // 全选时仍跳过已存在（可手动勾选）
    setSelected(
      new Set(
        candidates
          .map((c, i) => (c.already_exists ? -1 : i))
          .filter((i) => i >= 0),
      ),
    );
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function persistDatabases(next: string[]) {
    if (!next.length) {
      onError("请至少选择一个检索库");
      return;
    }
    setSavingDbs(true);
    onError("");
    try {
      await apiFetch<Project>(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ literature_databases: next }),
      });
      setSelectedDbs(next);
      onMessage(`已保存检索库：${next.join(", ")}`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "保存检索库失败");
    } finally {
      setSavingDbs(false);
    }
  }

  function toggleDatabase(id: string) {
    const next = selectedDbs.includes(id)
      ? selectedDbs.filter((x) => x !== id)
      : [...selectedDbs, id];
    void persistDatabases(next);
  }

  async function ping() {
    setBusy(true);
    onError("");
    onMessage(`正在探测 AUT→${selectedDbs.join("+").toUpperCase()}…（可能弹出浏览器）`);
    try {
      const res = await apiFetch<{
        ok: boolean;
        results: { ok: boolean; provider?: string; error?: string; final_url?: string }[];
      }>(`/projects/${projectId}/literature-search/ping`, { method: "POST" });
      if (res.ok) {
        onMessage(
          `连通正常：${res.results
            .map((r) => `${r.provider || "?"}${r.final_url ? ` (${r.final_url})` : ""}`)
            .join("；")}`,
        );
      } else {
        onError(res.results.map((r) => `${r.provider || "?"}: ${r.error || "失败"}`).join("; ") || "探测失败");
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "探测失败");
    } finally {
      setBusy(false);
    }
  }

  async function syncFromZotero() {
    setBusy(true);
    onError("");
    onMessage("正在从 Zotero 项目集合拉取…");
    try {
      const rows = await apiFetch<Literature[]>(
        `/zotero/projects/${projectId}/sync`,
        { method: "POST" },
      );
      onMessage(`已从 Zotero 同步 ${rows.length} 篇（含离线新增）`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "同步失败");
    } finally {
      setBusy(false);
    }
  }

  async function runSearch() {
    if (!outlineReady || !heading) {
      onError("请先在 Inputs 锁定论文大纲（C）");
      return;
    }
    if (!selectedDbs.length) {
      onError("请至少选择一个检索库");
      return;
    }
    setSearching(true);
    setBusy(true);
    onError("");
    onMessage(
      `检索中（${selectedDbs.join("+")}，每库最多 ${maxResults} 条）…将打开浏览器，约 30–90 秒`,
    );
    try {
      const body: Record<string, unknown> = {
        outline_heading: heading,
        max_results: maxResults,
        databases: selectedDbs,
      };
      if (query.trim()) body.query = query.trim();
      const res = await apiFetch<LiteratureSearchRun>(
        `/projects/${projectId}/literature-search`,
        { method: "POST", body: JSON.stringify(body) },
      );
      setRun(res);
      // 默认不勾选「已存在」项，避免重复入库
      setSelected(
        new Set(
          res.candidates
            .map((c, i) => (c.already_exists ? -1 : i))
            .filter((i) => i >= 0),
        ),
      );
      const existed = res.candidates.filter((c) => c.already_exists).length;
      onMessage(
        `找到 ${res.candidates.length} 条候选（query: ${res.query}）` +
          (res.deduped_count ? `，已去重 ${res.deduped_count} 条` : "") +
          (existed ? `，其中 ${existed} 条已在 Collection 中` : "") +
          "，请勾选后确认入库",
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : "检索失败");
      setRun(null);
      setSelected(new Set());
    } finally {
      setSearching(false);
      setBusy(false);
    }
  }

  async function confirmImport() {
    if (!run?.id) {
      onError("请先检索");
      return;
    }
    const indices = Array.from(selected).sort((a, b) => a - b);
    if (!indices.length) {
      onError("请至少勾选一篇");
      return;
    }
    setConfirming(true);
    setBusy(true);
    onError("");
    onMessage(`正在写入 Zotero（${indices.length} 篇）…`);
    try {
      const created = await apiFetch<Literature[]>(
        `/projects/${projectId}/literature-search/${run.id}/confirm`,
        { method: "POST", body: JSON.stringify({ indices }) },
      );
      onMessage(`已入库 ${created.length} 篇到章节「${run.outline_heading}」`);
      setSelected(new Set());
      setRun(null);
      await onReload();
      if (step < chapters.length - 1) {
        setStep((s) => s + 1);
        onMessage(
          `已入库 ${created.length} 篇。已进入下一章「${chapters[step + 1]?.heading}」`,
        );
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "入库失败");
    } finally {
      setConfirming(false);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="card space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold">按章文献向导</h2>
            <p className="mt-1 text-sm text-stone-500">
              逐章检索并确认入库。写作前会从 Zotero 项目集合重新拉取（支持离线增补）。
            </p>
          </div>
          {outlineReady && (
            <p className="text-sm text-stone-600">
              进度{" "}
              <span className="font-medium text-brand-700">
                {doneCount}/{chapters.length}
              </span>{" "}
              章已有文献
            </p>
          )}
        </div>

        {!outlineReady && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
            请先在「Inputs」锁定大纲后再检索。
          </p>
        )}

        {outlineReady && (
          <ol className="flex flex-wrap gap-2">
            {chapters.map((ch, idx) => {
              const count = confirmedByHeading.get(ch.heading) || 0;
              const active = idx === step;
              const done = count > 0;
              return (
                <li key={ch.heading}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => goChapter(idx)}
                    className={`rounded-md border px-2.5 py-1.5 text-left text-xs transition ${
                      active
                        ? "border-brand-600 bg-brand-50 text-brand-800"
                        : done
                          ? "border-stone-300 bg-stone-50 text-stone-700 hover:border-brand-400"
                          : "border-stone-200 text-stone-500 hover:border-stone-400"
                    }`}
                    title={ch.key_points || ch.heading}
                  >
                    <span className="font-medium">
                      {done ? "✓ " : ""}
                      {idx + 1}. {ch.heading}
                    </span>
                    {done ? (
                      <span className="mt-0.5 block text-[10px] text-stone-500">
                        {count} 篇
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {current && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-display text-base font-semibold">
              第 {step + 1}/{chapters.length} 章 · {current.heading}
            </h3>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy || step <= 0}
                onClick={() => goChapter(step - 1)}
              >
                上一章
              </button>
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy || step >= chapters.length - 1}
                onClick={() => goChapter(step + 1)}
              >
                下一章
              </button>
            </div>
          </div>

          {current.key_points ? (
            <div className="rounded-md border border-stone-100 bg-stone-50 px-3 py-2">
              <p className="text-xs font-medium text-stone-500">本章要点（可参考写检索词）</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-stone-700">
                {current.key_points}
              </p>
            </div>
          ) : (
            <p className="text-xs text-stone-400">本章大纲无 key_points / summary。</p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="label" htmlFor="lit-query">
                检索词（可空 = 使用测试默认词）
              </label>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  id="lit-query"
                  className="input flex-1"
                  placeholder="food delivery transformation"
                  value={query}
                  disabled={busy}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <button
                  type="button"
                  className="btn-outline shrink-0 text-sm"
                  disabled={busy || suggesting || !heading}
                  onClick={() => void suggestQuery()}
                  title={
                    openaiConfigured
                      ? "用 LLM 根据本章要点生成英文检索词"
                      : "未配置 Key 时使用规则回退词"
                  }
                >
                  {suggesting ? "生成中…" : "生成本章检索词"}
                </button>
              </div>
              <label className="mt-2 inline-flex items-center gap-2 text-xs text-stone-500">
                <input
                  type="checkbox"
                  checked={autoSuggest}
                  disabled={busy}
                  onChange={(e) => setAutoSuggest(e.target.checked)}
                />
                进章时自动生成
                {!openaiConfigured ? (
                  <span className="text-amber-700">· 当前无 OpenAI Key，将用规则词</span>
                ) : null}
              </label>
            </div>
            <div className="sm:col-span-2">
              <p className="label">检索库</p>
              <div className="mt-1 flex flex-wrap gap-3">
                {(providers.length
                  ? providers
                  : [
                      { id: "ieee", name: "IEEE Xplore", entry_url: "", implemented: true },
                      {
                        id: "acm",
                        name: "ACM Digital Library",
                        entry_url: "",
                        implemented: true,
                      },
                    ]
                ).map((p) => (
                  <label
                    key={p.id}
                    className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                      selectedDbs.includes(p.id)
                        ? "border-brand-500 bg-brand-50 text-brand-800"
                        : "border-stone-200 text-stone-600"
                    } ${!p.implemented || busy || savingDbs ? "opacity-60" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedDbs.includes(p.id)}
                      disabled={busy || savingDbs || !p.implemented}
                      onChange={() => toggleDatabase(p.id)}
                    />
                    <span>
                      {p.name}
                      {!p.implemented ? (
                        <span className="ml-1 text-xs text-stone-400">（未实现）</span>
                      ) : null}
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-stone-400">
                多选时每个库各取下方数量，再按 DOI/标题去重。勾选会写入本项目配置。
              </p>
            </div>
            <div>
              <label className="label" htmlFor="lit-max">
                每个库最多结果
              </label>
              <input
                id="lit-max"
                type="number"
                min={1}
                max={30}
                className="input"
                value={maxResults}
                disabled={busy}
                onChange={(e) => setMaxResults(Number(e.target.value) || 10)}
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-outline" disabled={busy} onClick={ping}>
              探测连通
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
              className="btn"
              disabled={busy || searching}
              onClick={runSearch}
            >
              {searching ? "检索中…" : "检索本章"}
            </button>
            <button
              type="button"
              className="btn-outline"
              disabled={busy || step >= chapters.length - 1}
              onClick={() => goChapter(step + 1)}
            >
              跳过本章
            </button>
          </div>
        </section>
      )}

      {run && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="font-display text-base font-semibold">候选列表</h3>
              <p className="text-xs text-stone-500">
                章节「{run.outline_heading}」· query「{run.query}」· {run.candidates.length}{" "}
                条
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy}
                onClick={() => selectAll(run.candidates)}
              >
                全选
              </button>
              <button
                type="button"
                className="btn-outline text-xs"
                disabled={busy}
                onClick={clearSelection}
              >
                清空
              </button>
              <button
                type="button"
                className="btn text-xs"
                disabled={busy || confirming || selected.size === 0}
                onClick={confirmImport}
              >
                {confirming ? "入库中…" : `确认入库（${selected.size}）`}
              </button>
            </div>
          </div>

          {!run.candidates.length ? (
            <p className="text-sm text-stone-500">无候选结果</p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {run.candidates.map((c, idx) => (
                <li key={`${c.title}-${idx}`} className="flex gap-3 py-4">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selected.has(idx)}
                    disabled={busy}
                    onChange={() => toggleIndex(idx)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium leading-snug text-ink">{c.title}</p>
                      {c.already_exists ? (
                        <span
                          className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800"
                          title={
                            c.existing_outline_heading
                              ? `已在章节「${c.existing_outline_heading}」`
                              : "已在本项目 Zotero Collection"
                          }
                        >
                          已存在
                          {c.existing_outline_heading
                            ? ` · ${c.existing_outline_heading}`
                            : ""}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm text-stone-600">
                      {(c.authors || []).join(", ") || "Unknown"} · {c.year || "n.d."}
                      {c.provider ? (
                        <span className="ml-2 text-xs uppercase text-brand-500">
                          {c.provider}
                        </span>
                      ) : null}
                    </p>
                    {c.doi && (
                      <p className="mt-0.5 text-xs text-stone-500">DOI: {c.doi}</p>
                    )}
                    {c.abstract && (
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-stone-600">
                        {c.abstract}
                      </p>
                    )}
                    {c.url && (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-block text-xs text-brand-600 underline"
                      >
                        打开原文
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="card">
        <h2 className="mb-4 font-display text-lg font-semibold">已确认文献库</h2>
        <ZoteroList items={literatures} onToggle={onToggleLit} />
      </section>
    </div>
  );
}
