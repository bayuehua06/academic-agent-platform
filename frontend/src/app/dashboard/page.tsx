"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, MouseEvent, useEffect, useState } from "react";
import { apiFetch, clearToken, Project } from "@/lib/api";
import { STATUS_LABELS, statusColor } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<Project[]>("/projects");
      setProjects(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login");
      return;
    }
    load();
  }, [router]);

  async function createProject(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      const p = await apiFetch<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({ title: title.trim() }),
      });
      setTitle("");
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function deleteProject(e: MouseEvent, p: Project) {
    e.preventDefault();
    e.stopPropagation();
    const ok = window.confirm(
      `确定删除项目「${p.title}」？本地文献镜像与草稿将一并删除（Zotero 远端集合不会自动删）。`,
    );
    if (!ok) return;
    setBusyId(p.id);
    setError("");
    try {
      await apiFetch(`/projects/${p.id}`, { method: "DELETE" });
      setProjects((prev) => prev.filter((x) => x.id !== p.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  }

  function logout() {
    clearToken();
    router.push("/login");
  }

  return (
    <main className="min-h-screen">
      <header className="border-b border-stone-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <div>
            <h1 className="font-display text-2xl font-bold text-brand-700">
              Academic Agent
            </h1>
            <p className="text-xs text-stone-500">项目管理看板</p>
          </div>
          <button type="button" className="btn-outline" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-4 py-8">
        <form onSubmit={createProject} className="card mb-8 flex flex-col gap-3 sm:flex-row">
          <input
            className="input flex-1"
            placeholder="新项目标题…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button type="submit" className="btn">
            创建项目
          </button>
        </form>

        {error && <p className="mb-4 text-sm text-accent">{error}</p>}
        {loading ? (
          <p className="text-sm text-stone-500">加载中…</p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-stone-500">还没有项目，先创建一个吧。</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {projects.map((p) => (
              <div key={p.id} className="card relative transition hover:border-brand-500">
                <Link href={`/projects/${p.id}`} className="block pr-16">
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="font-display text-lg font-semibold">{p.title}</h2>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${statusColor(p.status)}`}>
                      {STATUS_LABELS[p.status] || p.status}
                    </span>
                  </div>
                  <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-stone-500">
                    <div>
                      <dt>文献</dt>
                      <dd className="text-sm font-medium text-ink">{p.literature_count}</dd>
                    </div>
                    <div>
                      <dt>最新版本</dt>
                      <dd className="text-sm font-medium text-ink">
                        {p.latest_version != null ? `v${p.latest_version}` : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>源文档</dt>
                      <dd className="text-sm font-medium text-ink">
                        {p.source_document_count ?? 0}
                      </dd>
                    </div>
                    <div>
                      <dt>大纲</dt>
                      <dd className="text-sm font-medium text-ink">
                        {p.outline_ready ? "已锁定" : "未就绪"}
                      </dd>
                    </div>
                  </dl>
                </Link>
                <button
                  type="button"
                  className="btn-outline absolute right-3 top-3 text-xs text-red-700 hover:border-red-400"
                  disabled={busyId === p.id}
                  onClick={(e) => void deleteProject(e, p)}
                >
                  {busyId === p.id ? "…" : "删除"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
