#!/usr/bin/env bash
set -euo pipefail

# Start headless Blender bridge in background (localhost only inside container)
BLENDER_PORT="${BLENDER_MCP_PORT:-9876}"
BLENDER_TOKEN="${BLENDER_MCP_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
export BLENDER_MCP_PORT="$BLENDER_PORT"
export BLENDER_MCP_TOKEN="$BLENDER_TOKEN"
export BLENDER_MCP_HOST="127.0.0.1"

LAUNCH_ARGS=(--host 127.0.0.1 --port "$BLENDER_PORT")
if [[ "${BLENDER_MCP_ALLOW_PYTHON:-false}" =~ ^(true|1|yes|on|confirm)$ ]]; then
  LAUNCH_ARGS+=(--allow-python)
fi

uv run --no-sync blender-mcp launch "${LAUNCH_ARGS[@]}" &
BLENDER_PID=$!

cleanup() {
  kill "$BLENDER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait briefly for bridge handshake readiness
for _ in $(seq 1 40); do
  if uv run --no-sync blender-mcp doctor 2>/dev/null | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("bridge_connected") else 1)'; then
    break
  fi
  sleep 0.5
done

exec uv run --no-sync blender-mcp serve \
  --transport http \
  --host "${BLENDER_MCP_HTTP_HOST:-0.0.0.0}" \
  --port "${BLENDER_MCP_HTTP_PORT:-8765}" \
  --profile "${BLENDER_MCP_PROFILE:-full}"
