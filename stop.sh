#!/bin/bash
# Academic Agent Platform 停止脚本
# 停止前后端开发进程，并释放固定端口

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

FRONTEND_PORT=1980
BACKEND_PORT=1976

echo "🛑 停止 Academic Agent Platform 服务..."

echo "🔧 停止后端 (uvicorn)..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "academic-agent-platform/backend/.venv/bin/uvicorn" 2>/dev/null || true

echo "🎨 停止前端 (Next.js)..."
pkill -f "next dev -p ${FRONTEND_PORT}" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true

echo "🔄 停止并发/脚本进程..."
pkill -f "scripts/dev.mjs" 2>/dev/null || true
pkill -f "scripts/run-backend.mjs" 2>/dev/null || true
pkill -f "concurrently" 2>/dev/null || true

kill_port() {
  local port="$1"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "⚠️  端口 ${port} 仍被占用，强制终止..."
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | xargs kill -9 2>/dev/null || true
  fi
}

echo "🔍 检查端口占用..."
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

sleep 0.3
echo "✅ Academic Agent Platform 服务已停止"
