# MCP Client Setup Guide

`blender-mcp` works with any **Model Context Protocol** client over `stdio` or `Streamable HTTP`.

## 1. Prepare Blender

### GUI Mode (Blender 3.6 LTS → 5.3+)
```bash
uv run blender-mcp install-addon
```
Open Blender, press `N` in the 3D Viewport → open the **MCP** tab → confirm `Status: Running`.

### Headless Mode (No GUI / CI / Render Farm)
```bash
uv run blender-mcp launch --port 9876
```

### Quick Diagnostics
```bash
uv run blender-mcp doctor
```

---

## 2. Configuration Snippets by Client

> **Tip for clients with tool-count limits (e.g., Cursor's ~40-tool cap):** set `"BLENDER_MCP_PROFILE": "minimal"` (loads fewer than 20 initial tools) and let the agent activate modules on demand via `enable_toolset("nodes")`, `enable_toolset("animation")`, `enable_toolset("integrations")`, etc.

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "blender": {
      "command": "uv",
      "args": ["--directory", "/PATH/TO/mcp-servers/blender", "run", "blender-mcp"],
      "env": {
        "BLENDER_MCP_ALLOW_PYTHON": "false",
        "BLENDER_MCP_PROFILE": "modeling"
      }
    }
  }
}
```

### Claude Code
```bash
claude mcp add blender \
  -e BLENDER_MCP_ALLOW_PYTHON=false \
  -e BLENDER_MCP_PROFILE=full \
  -- uv --directory /PATH/TO/mcp-servers/blender run blender-mcp
```

### Cursor (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "blender": {
      "command": "uv",
      "args": ["--directory", "/PATH/TO/mcp-servers/blender", "run", "blender-mcp"],
      "env": {
        "BLENDER_MCP_ALLOW_PYTHON": "false",
        "BLENDER_MCP_PROFILE": "minimal"
      }
    }
  }
}
```

### VS Code Copilot (`.vscode/mcp.json`)
```json
{
  "servers": {
    "blender": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/PATH/TO/mcp-servers/blender", "run", "blender-mcp"],
      "env": {
        "BLENDER_MCP_ALLOW_PYTHON": "false",
        "BLENDER_MCP_PROFILE": "modeling"
      }
    }
  }
}
```

### Antigravity / Windsurf / Gemini CLI / Codex / Zed
```json
{
  "mcpServers": {
    "blender": {
      "command": "uv",
      "args": ["--directory", "/PATH/TO/mcp-servers/blender", "run", "blender-mcp"],
      "env": {
        "BLENDER_MCP_ALLOW_PYTHON": "false",
        "BLENDER_MCP_PROFILE": "full"
      }
    }
  }
}
```

---

## 3. Streamable HTTP Transport (Local or Docker)

```bash
BLENDER_MCP_HTTP_BEARER_TOKEN="replace-with-strong-secret" \
uv run blender-mcp serve --transport http --host 127.0.0.1 --port 8765 --profile full
```

Or via headless Docker:
```bash
docker compose -f docker/docker-compose.yml up --build
```

---

## 4. Per-Client Manual Verification Checklist

- [ ] `get_blender_info` returns the connected Blender version and runtime `capabilities`.
- [ ] `capture_multiview` displays the labeled 2×2 PNG contact sheet inline in chat.
- [ ] `list_toolsets` / `enable_toolset` updates the client's active tool list.
- [ ] `blender://scene` appears under Resources and updates after scene edits.
- [ ] Guided Prompts (`product_shot`, `turntable_animation`, etc.) appear in the prompts menu.
- [ ] `execute_python` is hidden and blocked when `BLENDER_MCP_ALLOW_PYTHON=false`.
