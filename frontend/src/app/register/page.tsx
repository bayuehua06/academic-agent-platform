"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { login, register } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(username, email, password);
      await login(username, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-paper to-stone-100 px-4">
      <div className="w-full max-w-md">
        <h1 className="font-display text-3xl font-bold text-brand-700">创建账号</h1>
        <form onSubmit={onSubmit} className="card mt-8 space-y-4">
          <div>
            <label className="label" htmlFor="username">
              用户名
            </label>
            <input
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="email">
              邮箱
            </label>
            <input
              id="email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
              minLength={6}
              required
            />
          </div>
          {error && <p className="text-sm text-accent">{error}</p>}
          <button type="submit" className="btn w-full" disabled={loading}>
            {loading ? "提交中…" : "注册"}
          </button>
          <p className="text-center text-sm text-stone-500">
            已有账号？{" "}
            <Link href="/login" className="text-brand-600 underline">
              登录
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
