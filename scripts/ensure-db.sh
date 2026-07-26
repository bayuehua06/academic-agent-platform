#!/bin/bash
# Academic Agent Platform — 确保 PostgreSQL 可用
# 优先 Docker Compose；否则使用本机 PostgreSQL（Homebrew）创建角色/库

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

DB_USER="${DB_USER:-academic}"
DB_PASSWORD="${DB_PASSWORD:-academic_secret}"
DB_NAME="${DB_NAME:-academic_agent}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

echo "🗄️  检查数据库 ${DB_NAME} @ ${DB_HOST}:${DB_PORT} ..."

# ---------- Docker Compose ----------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "🐳 检测到 Docker，启动 docker compose 数据库..."
  docker compose up -d
  # 等待就绪
  for i in $(seq 1 30); do
    if docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
      echo "✅ Docker PostgreSQL 已就绪"
      exit 0
    fi
    sleep 1
  done
  echo "❌ Docker PostgreSQL 启动超时"
  exit 1
fi

# ---------- 本机 PostgreSQL ----------
if ! command -v psql >/dev/null 2>&1; then
  echo "❌ 未找到 Docker，也未找到 psql。"
  echo "   请安装 Docker Desktop，或：brew install postgresql@16 && brew services start postgresql@16"
  exit 1
fi

if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
  echo "❌ 本机 PostgreSQL 未在 ${DB_HOST}:${DB_PORT} 监听。"
  echo "   可尝试：brew services start postgresql@16"
  echo "   或安装 Docker 后使用：docker compose up -d"
  exit 1
fi

# 选择有建库权限的本机超级用户（优先当前用户）
ADMIN_USER="${PGUSER:-}"
if [ -z "$ADMIN_USER" ]; then
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
    ADMIN_USER="$(whoami)"
  elif psql -h "$DB_HOST" -p "$DB_PORT" -U songchen -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
    ADMIN_USER="songchen"
  elif psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
    ADMIN_USER="postgres"
  else
    echo "❌ 无法以本机用户连接 PostgreSQL（需要超级用户创建角色 ${DB_USER}）"
    echo "   请设置 PGUSER=你的超级用户 后重试"
    exit 1
  fi
fi

echo "🔧 使用本机管理员「${ADMIN_USER}」初始化角色与数据库..."

psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d postgres <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

DB_EXISTS="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" || true)"
if [ "$DB_EXISTS" != "1" ]; then
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
fi

psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d "$DB_NAME" <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER SCHEMA public OWNER TO ${DB_USER};
SQL

if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c 'SELECT 1' >/dev/null 2>&1; then
  echo "✅ 本机 PostgreSQL 已就绪（用户 ${DB_USER} / 库 ${DB_NAME}）"
  exit 0
fi

echo "❌ 角色 ${DB_USER} 无法连接数据库 ${DB_NAME}"
exit 1
