"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, Literature, Project } from "@/lib/api";

export type AccessibleCollection = {
  key: string;
  name: string;
  library_type: string;
  library_id: string;
  library_name: string;
};

type Props = {
  projectId: string;
  project: Project;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
  onReload: () => Promise<void>;
};

function collectionLabel(c: AccessibleCollection): string {
  const lib =
    c.library_type === "group"
      ? `Group · ${c.library_name}`
      : `个人 · ${c.library_name}`;
  return `${c.name} （${lib}）`;
}

export function ZoteroBindingPanel({
  projectId,
  project,
  busy,
  setBusy,
  onMessage,
  onError,
  onReload,
}: Props) {
  const bound = Boolean(project.zotero_collection_id && project.zotero_binding_mode);
  const [collections, setCollections] = useState<AccessibleCollection[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [selectedKey, setSelectedKey] = useState("");
  const [showRebind, setShowRebind] = useState(false);

  const selected = useMemo(
    () =>
      collections.find(
        (c) => `${c.library_type}:${c.library_id}:${c.key}` === selectedKey,
      ),
    [collections, selectedKey],
  );

  const loadCollections = useCallback(async () => {
    setLoadingList(true);
    onError("");
    try {
      const res = await apiFetch<{ collections: AccessibleCollection[] }>(
        "/zotero/accessible-collections",
      );
      setCollections(res.collections || []);
      if (!(res.collections || []).length) {
        onMessage("未发现可访问的顶层 Collection（可先选「完全新建」）");
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "列举 Collection 失败");
      setCollections([]);
    } finally {
      setLoadingList(false);
    }
  }, [onError, onMessage]);

  useEffect(() => {
    if (!bound || showRebind) {
      void loadCollections();
    }
  }, [bound, showRebind, loadCollections]);

  async function syncFromZotero() {
    setBusy(true);
    onError("");
    onMessage("正在从 Zotero 重新同步（保留已有章节分配）…");
    try {
      const rows = await apiFetch<Literature[]>(
        `/zotero/projects/${projectId}/sync`,
        { method: "POST" },
      );
      onMessage(`已同步 ${rows.length} 篇；原章节分配在仍存在的条目上保留`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "同步失败");
    } finally {
      setBusy(false);
    }
  }

  async function bindCreate() {
    if (
      bound &&
      !window.confirm(
        "确认改为「完全新建」后，才会替换当前绑定并清空本地文献与章节分配。打开本面板本身不会删除分配。继续？",
      )
    ) {
      return;
    }
    setBusy(true);
    onError("");
    onMessage("正在新建项目 Collection + 章节子集合…");
    try {
      const res = await apiFetch<{
        zotero_collection_id: string;
        synced_count?: number;
        assignments_cleared?: boolean;
      }>(`/zotero/projects/${projectId}/binding`, {
        method: "POST",
        body: JSON.stringify({ mode: "create" }),
      });
      onMessage(
        `已绑定（新建）：${res.zotero_collection_id}` +
          (res.assignments_cleared ? "（已替换旧绑定，章节分配已清空）" : ""),
      );
      setShowRebind(false);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "绑定失败");
    } finally {
      setBusy(false);
    }
  }

  async function bindAttach() {
    if (!selected) {
      onError("请先选择一个已有 Collection");
      return;
    }
    const sameAsCurrent =
      bound &&
      project.zotero_binding_mode === "attach" &&
      project.zotero_collection_id === selected.key &&
      project.zotero_library_type === selected.library_type &&
      String(project.zotero_library_id || "") === String(selected.library_id);
    if (
      bound &&
      !sameAsCurrent &&
      !window.confirm(
        "确认挂接该集合后，才会替换当前绑定并清空本地文献与章节分配。仅打开「更换绑定」不会删除。继续？",
      )
    ) {
      return;
    }
    setBusy(true);
    onError("");
    onMessage(
      sameAsCurrent
        ? `正在重新同步「${selected.name}」（保留章节分配）…`
        : `正在挂接「${selected.name}」并拉取文献…`,
    );
    try {
      const res = await apiFetch<{
        zotero_collection_id: string;
        synced_count?: number;
        assignments_cleared?: boolean;
      }>(`/zotero/projects/${projectId}/binding`, {
        method: "POST",
        body: JSON.stringify({
          mode: "attach",
          collection_key: selected.key,
          library_type: selected.library_type,
          library_id: selected.library_id,
        }),
      });
      onMessage(
        sameAsCurrent || !res.assignments_cleared
          ? `已同步 Collection ${res.zotero_collection_id}（${res.synced_count ?? 0} 篇）；章节分配已保留`
          : `已挂接 Collection ${res.zotero_collection_id}，同步 ${res.synced_count ?? 0} 篇（旧分配已清空，请重新按章勾选）`,
      );
      setShowRebind(false);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "挂接失败");
    } finally {
      setBusy(false);
    }
  }

  if (bound && !showRebind) {
    return (
      <section className="card space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold">Zotero 绑定</h2>
            <p className="mt-1 text-sm text-stone-500">
              模式{" "}
              <span className="font-medium text-brand-700">
                {project.zotero_binding_mode === "attach" ? "挂接已有" : "完全新建"}
              </span>
              {" · "}
              {project.zotero_library_type === "group" ? "Group" : "个人库"}
              {project.zotero_library_id ? ` ${project.zotero_library_id}` : ""}
              {" · "}
              Collection{" "}
              <code className="text-xs">{project.zotero_collection_id}</code>
            </p>
            <p className="mt-1 text-xs text-stone-400">
              Zotero 中新增文献后，点「重新同步」拉取；不会清空已有章节分配。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn text-xs"
              disabled={busy}
              onClick={() => void syncFromZotero()}
            >
              重新同步
            </button>
            <button
              type="button"
              className="btn-outline text-xs"
              disabled={busy}
              onClick={() => setShowRebind(true)}
            >
              更换绑定
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="card space-y-4">
      <div>
        <h2 className="font-display text-lg font-semibold">
          {bound ? "更换 Zotero 绑定" : "绑定 Zotero Collection"}
        </h2>
        <p className="mt-1 text-sm text-stone-500">
          二选一：挂接 Key 可访问的已有顶层集合（个人或 Group），或按项目标题完全新建（含章节子集合）。
          {bound
            ? " 仅打开本面板不会删除章节分配；确认挂接另一个集合（或改为新建）后才会清空并替换。"
            : ""}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <label className="label mb-0" htmlFor="zotero-attach-select">
            已有 Collection
          </label>
          <button
            type="button"
            className="btn-outline text-xs"
            disabled={busy || loadingList}
            onClick={() => void loadCollections()}
          >
            {loadingList ? "刷新中…" : "刷新列表"}
          </button>
        </div>
        <select
          id="zotero-attach-select"
          className="input"
          disabled={busy || loadingList || !collections.length}
          value={selectedKey}
          onChange={(e) => setSelectedKey(e.target.value)}
        >
          <option value="">
            {loadingList
              ? "加载中…"
              : collections.length
                ? "请选择…"
                : "（无可用顶层集合）"}
          </option>
          {collections.map((c) => {
            const id = `${c.library_type}:${c.library_id}:${c.key}`;
            return (
              <option key={id} value={id}>
                {collectionLabel(c)}
              </option>
            );
          })}
        </select>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn"
          disabled={busy || !selected}
          onClick={() => void bindAttach()}
        >
          挂接所选集合
        </button>
        <button
          type="button"
          className="btn-outline"
          disabled={busy}
          onClick={() => void bindCreate()}
        >
          完全新建
        </button>
        {bound ? (
          <button
            type="button"
            className="btn-outline"
            disabled={busy}
            onClick={() => setShowRebind(false)}
          >
            取消
          </button>
        ) : null}
      </div>
    </section>
  );
}
