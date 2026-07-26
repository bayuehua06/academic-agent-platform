#!/bin/bash
# Academic Agent Platform 启动脚本
# 初始化依赖与数据库，并同时启动前端(1980) / 后端(1976)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

FRONTEND_PORT=1980
BACKEND_PORT=1976

echo "🚀 启动 Academic Agent Platform..."

if [ ! -f "package.json" ] || [ ! -d "backend" ] || [ ! -d "frontend" ]; then
  echo "❌ 请在项目根目录运行此脚本"
  exit 1
fi

# 先停止旧进程
./stop.sh

ask_kill_port() {
  local port="$1"
  local label="$2"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "⚠️  端口 ${port} (${label}) 已被占用"
    read -r -p "是否要终止占用端口的进程？(y/N): " -n 1 REPLY
    echo
    if [[ ${REPLY:-} =~ ^[Yy]$ ]]; then
      lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | xargs kill -9 2>/dev/null || true
      echo "✅ 已终止端口 ${port} 的进程"
    else
      echo "❌ 启动失败，请手动释放端口：lsof -ti:${port} | xargs kill"
      exit 1
    fi
  fi
}

echo "🔍 检查端口占用情况..."
ask_kill_port "$BACKEND_PORT" "后端"
ask_kill_port "$FRONTEND_PORT" "前端"

# ---------- 环境文件 ----------
if [ ! -f "backend/.env" ]; then
  echo "📝 创建 backend/.env ..."
  cp backend/.env.example backend/.env
fi
if [ ! -f "frontend/.env.local" ]; then
  echo "📝 创建 frontend/.env.local ..."
  cp frontend/.env.example frontend/.env.local
fi

# ---------- 依赖 ----------
if [ ! -d "node_modules" ]; then
  echo "📦 安装根目录依赖..."
  npm install
fi

if [ ! -d "frontend/node_modules" ]; then
  echo "📦 安装前端依赖..."
  npm install --prefix frontend
fi

if ! npm list concurrently >/dev/null 2>&1; then
  echo "📦 安装 concurrently..."
  npm install concurrently
fi

# 后端 Python 虚拟环境
if [ ! -d "backend/.venv" ]; then
  echo "🐍 创建后端虚拟环境..."
  python3 -m venv backend/.venv
fi

# shellcheck disable=SC1091
source backend/.venv/bin/activate
if ! python -c "import fastapi, uvicorn, sqlalchemy" >/dev/null 2>&1; then
  echo "📦 安装后端 Python 依赖..."
  pip install -r backend/requirements.txt
fi
# 开发测试依赖（可选，失败不阻断启动）
if [ -f "backend/requirements-dev.txt" ]; then
  pip install -q -r backend/requirements-dev.txt >/dev/null 2>&1 || true
fi
deactivate 2>/dev/null || true

# ---------- 数据库 ----------
chmod +x scripts/ensure-db.sh
./scripts/ensure-db.sh

# ---------- 启动 ----------
echo ""
echo "🎯 启动前后端..."
echo "   前端：http://localhost:${FRONTEND_PORT}"
echo "   后端：http://localhost:${BACKEND_PORT}"
echo "   API ：http://localhost:${BACKEND_PORT}/docs"
echo ""
echo "🛑 按 Ctrl+C 停止；或另开终端执行 ./stop.sh"
echo ""

npm run dev
