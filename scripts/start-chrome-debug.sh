#!/bin/bash
# 以远程调试模式启动「专用」Chrome（独立 user-data-dir）。
# 新版 Chrome 会对默认 Profile 静默忽略 --remote-debugging-port，必须用独立目录。
#
# 用法：
#   1) Cmd+Q 完全退出所有 Chrome
#   2) ./scripts/start-chrome-debug.sh
#   3) 在弹出的窗口登录 Google，打开 NotebookLM
#   4) 平台点「更新」

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${CHROME_DEBUG_PORT:-9222}"
CDP="http://127.0.0.1:${PORT}"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# 独立目录（不要用 ~/Library/Application Support/Google/Chrome）
USER_DATA_DIR="${CHROME_DEBUG_USER_DATA_DIR:-${HOME}/.academic-agent-platform/chrome-debug-profile}"
LOG="/tmp/academic-chrome-debug.log"

if [ ! -x "$CHROME_BIN" ]; then
  echo "❌ 未找到 Google Chrome: $CHROME_BIN"
  exit 1
fi

# 已在调试端口则直接可用
if curl -sf "${CDP}/json/version" >/dev/null 2>&1; then
  echo "✅ Chrome 调试端口已就绪: ${CDP}"
  curl -s "${CDP}/json/version"
  echo
  echo "请确认 backend/.env: CHROME_CDP_URL=${CDP}"
  exit 0
fi

# 若仍有 Chrome 在跑，调试端口往往起不来 / 会连到错误实例
if pgrep -x "Google Chrome" >/dev/null 2>&1 || pgrep -f "Google Chrome.app" >/dev/null 2>&1; then
  echo "⚠️  检测到 Chrome 仍在运行。"
  echo "   新版 Chrome 不会在「默认用户目录」上开放 9222，且多实例会冲突。"
  echo "   请先完全退出：菜单栏 Chrome → 退出 Google Chrome（Cmd+Q）"
  echo "   然后再运行本脚本。"
  exit 1
fi

mkdir -p "$USER_DATA_DIR"

echo "🚀 启动专用调试 Chrome..."
echo "   CDP:           ${CDP}"
echo "   user-data-dir: ${USER_DATA_DIR}"
echo "   （首次需在此窗口登录 Google / NotebookLM，以后可复用）"
echo ""

# 关键：不要用系统默认 Chrome 目录；必须自定义 user-data-dir 调试端口才会生效
"$CHROME_BIN" \
  --remote-debugging-port="${PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${USER_DATA_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  "https://notebooklm.google.com/" \
  >"$LOG" 2>&1 &

CHROME_PID=$!
echo "Chrome pid=${CHROME_PID}，等待端口..."

for i in $(seq 1 40); do
  if curl -sf "${CDP}/json/version" >/dev/null 2>&1; then
    echo "✅ Chrome 调试端口已就绪: ${CDP}"
    curl -s "${CDP}/json/version"
    echo
    echo "请在 backend/.env 写入（若尚未写入）："
    echo "  CHROME_CDP_URL=${CDP}"
    echo ""
    echo "然后重启后端（./stop.sh && ./start.sh），在平台点「更新」。"
    # 同步提示写入项目 .env（不覆盖其它项，仅确保 CDP 行存在）
    ENV_FILE="${ROOT_DIR}/backend/.env"
    if [ -f "$ENV_FILE" ]; then
      if grep -q '^CHROME_CDP_URL=' "$ENV_FILE"; then
        sed -i.bak "s|^CHROME_CDP_URL=.*|CHROME_CDP_URL=${CDP}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
      else
        echo "CHROME_CDP_URL=${CDP}" >>"$ENV_FILE"
      fi
      echo "已更新 ${ENV_FILE} 中的 CHROME_CDP_URL"
    fi
    exit 0
  fi
  # 进程挂了
  if ! kill -0 "$CHROME_PID" 2>/dev/null; then
    echo "❌ Chrome 进程已退出，日志："
    tail -30 "$LOG" || true
    exit 1
  fi
  sleep 0.5
done

echo "❌ 等待调试端口超时。常见原因："
echo "   - 未真正退出旧 Chrome"
echo "   - 端口 ${PORT} 被占用"
echo "日志: $LOG"
tail -40 "$LOG" || true
lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
exit 1
