#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
PORT=5176

echo
echo "=== hermes-agent-provider · 设置页（macOS）==="
echo "地址：http://127.0.0.1:$PORT"
echo

if [[ ! -f "$FRONTEND/package.json" ]]; then
  echo "[错误] 找不到 frontend/package.json"
  exit 1
fi

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo "[错误] 需要 Node.js 18+ 与 npm"
  exit 1
fi

cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  echo "[信息] 正在 npm install ..."
  npm install
fi

echo "[启动] npm run dev"
echo "请先开后端 8765。"
exec npm run dev
