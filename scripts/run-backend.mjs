#!/usr/bin/env node
/**
 * 使用 backend/.venv 启动 uvicorn（端口 1976）。
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(__dirname, "../backend");
const BACKEND_PORT = 1976;

const isWin = process.platform === "win32";
const venvUvicorn = path.join(
  backendDir,
  ".venv",
  isWin ? "Scripts/uvicorn.exe" : "bin/uvicorn",
);

if (!fs.existsSync(venvUvicorn)) {
  console.error(
    `\n❌ 未找到后端虚拟环境: ${venvUvicorn}\n` +
      `请先执行:\n` +
      `  cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt\n`,
  );
  process.exit(1);
}

const child = spawn(
  venvUvicorn,
  ["main:app", "--reload", "--host", "0.0.0.0", "--port", String(BACKEND_PORT)],
  {
    cwd: backendDir,
    stdio: "inherit",
    env: { ...process.env },
  },
);

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
