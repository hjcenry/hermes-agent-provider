#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo
echo "=== hermes-agent-provider · 一键启动（macOS）==="
echo "后端 http://127.0.0.1:8765  ·  设置页 http://127.0.0.1:5176"
echo
"$ROOT/scripts/mac/start-backend.sh" &
exec "$ROOT/scripts/mac/start-frontend.sh"
