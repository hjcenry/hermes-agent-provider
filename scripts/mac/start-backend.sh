#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
VENV_PY="$VENV/bin/python"
REQ="$BACKEND/requirements.txt"
PORT=8765

echo
echo "=== hermes-agent-provider · 后端（macOS）==="
echo "仓库：$ROOT"
echo "地址：http://127.0.0.1:$PORT/healthz"
echo

if [[ ! -f "$BACKEND/app/main.py" ]]; then
  echo "[错误] 找不到 backend/app/main.py，请在仓库的 scripts/mac 下运行本脚本。"
  exit 1
fi

if [[ ! -f "$ROOT/config/secrets.env" ]]; then
  if [[ ! -f "$ROOT/config/secrets.env.example" ]]; then
    echo "[错误] 找不到 config/secrets.env.example，无法创建 secrets.env。"
    exit 1
  fi
  cp "$ROOT/config/secrets.env.example" "$ROOT/config/secrets.env"
  echo "[信息] 已从 example 创建 config/secrets.env，请尽快改 PROXY_API_KEY。"
fi
if [[ ! -f "$ROOT/config/local.yaml" && -f "$ROOT/config/local.yaml.example" ]]; then
  cp "$ROOT/config/local.yaml.example" "$ROOT/config/local.yaml"
  echo "[信息] 已从 example 创建 config/local.yaml。"
fi
mkdir -p "$ROOT/data/workspace"

pick_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "[错误] 未找到 Python 3.11+。请先安装，任选一种："
  echo "       brew install python@3.12"
  echo "       或从 https://www.python.org/downloads/ 安装，然后重新打开终端再运行。"
  exit 1
fi
echo "[检查] 系统 Python：$PY"

if [[ ! -x "$VENV_PY" ]]; then
  echo "[信息] 未找到虚拟环境，正在创建 backend/.venv ..."
  "$PY" -m venv "$VENV"
fi

echo "[检查] Python 包..."
if ! "$VENV_PY" -c "import fastapi, uvicorn, yaml, pydantic, httpx, dotenv, qoder_agent_sdk, cursor_sdk" >/dev/null 2>&1; then
  echo "[信息] 依赖不完整，正在 pip install -r backend/requirements.txt"
  "$VENV_PY" -m pip install -U pip
  "$VENV_PY" -m pip install -r "$REQ"
fi

echo
echo "[启动] uvicorn app.main:create_app --factory --host 127.0.0.1 --port $PORT"
echo "改 Python 后必须停掉本进程再重新运行本脚本（未开 --reload）。"
echo
cd "$BACKEND"
exec "$VENV_PY" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $PORT
