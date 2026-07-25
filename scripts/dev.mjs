#!/usr/bin/env node
/**
 * 开发启动脚本：检查固定端口，同时启动前后端。
 * 前端 1980 / 后端 1976；若端口占用则提示先 kill。
 */

import { execSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

const FRONTEND_PORT = 1980;
const BACKEND_PORT = 1976;

function listPortPids(port) {
  try {
    const out = execSync(`lsof -nP -iTCP:${port} -sTCP:LISTEN`, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    const lines = out.trim().split("\n").slice(1);
    const pids = new Set();
    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      if (parts[1]) pids.add(parts[1]);
    }
    return [...pids];
  } catch {
    return [];
  }
}

function reportOccupied() {
  const occupied = [];
  for (const [name, port] of [
    ["frontend", FRONTEND_PORT],
    ["backend", BACKEND_PORT],
  ]) {
    const pids = listPortPids(port);
    if (pids.length) {
      occupied.push({ name, port, pids });
    }
  }
  return occupied;
}

const busy = reportOccupied();
if (busy.length) {
  console.error("\n❌ 端口已被占用，请先 kill 后再启动：\n");
  for (const item of busy) {
    console.error(
      `  ${item.name}  :${item.port}  →  PID ${item.pids.join(", ")}`,
    );
    console.error(`    kill ${item.pids.join(" ")}`);
  }
  console.error("\n或一键释放：");
  const allPids = [...new Set(busy.flatMap((b) => b.pids))];
  console.error(`  kill ${allPids.join(" ")}\n`);
  process.exit(1);
}

console.log(
  `\n🚀 启动开发环境  frontend :${FRONTEND_PORT}  |  backend :${BACKEND_PORT}\n`,
);

const require = createRequire(import.meta.url);
let concurrently;
try {
  concurrently = require("concurrently");
} catch {
  console.error(
    "未找到 concurrently，请先在项目根目录执行: npm install\n",
  );
  process.exit(1);
}

const { result } = concurrently(
  [
    {
      command: "node scripts/run-backend.mjs",
      name: "backend",
      prefixColor: "cyan",
      cwd: root,
    },
    {
      command: "npm run dev --prefix frontend",
      name: "frontend",
      prefixColor: "magenta",
      cwd: root,
    },
  ],
  {
    prefix: "name",
    killOthersOn: ["failure", "success"],
    restartTries: 0,
  },
);

result.then(
  () => process.exit(0),
  () => process.exit(1),
);

// 捕获 Ctrl+C，结束子进程
process.on("SIGINT", () => {
  process.exit(0);
});
