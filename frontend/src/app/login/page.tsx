"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-paper to-stone-100 px-4">
      <div className="w-full max-w-md">
        <h1 className="font-display text-3xl font-bold text-brand-700">
          Academic Agent
        </h1>
        <p className="mt-2 text-sm text-stone-600">
          登录以管理学术项目、文献与 APA 草稿
        </p>
        <form onSubmit={onSubmit} className="card mt-8 space-y-4">
          <div>
            <label className="label" htmlFor="username">
              用户名或邮箱
            </label>
            <input
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="song.chen 或邮箱"
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="password">
              密码
            </label>
            <input
              id="password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-sm text-accent">{error}</p>}
          <button type="submit" className="btn w-full" disabled={loading}>
            {loading ? "登录中…" : "登录"}
          </button>
          <p className="text-center text-sm text-stone-500">
            没有账号？{" "}
            <Link href="/register" className="text-brand-600 underline">
              注册
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
