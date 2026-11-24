> Part of [mcp-servers](../README.md) — a curated collection of Model Context Protocol (MCP) servers for desktop and creative software.

# `blender-mcp` v1.0

A production-grade **Model Context Protocol (MCP)** server connecting AI agents from any MCP-compatible tool (Claude Desktop, Claude Code, Cursor, VS Code Copilot, Gemini CLI, Antigravity, Windsurf, Codex, Zed, and more) to **Blender 3D** (**Blender 3.6 LTS → 5.3+**).

## Highlights

- **Full 3D Pipeline (128 semantic tools across 19 toolsets):** scene inspection, objects, collections, `bmesh` modeling, typed modifiers, UVs, PBR materials, lighting & cameras, animation (Blender 5.x Slotted Actions + classic 3.6–4.3 Actions), rigging/IK, physics, sculpt, Grease Pencil (v2 + v3), Cycles/EEVEE/Workbench rendering, 3D I/O (glTF/GLB, FBX, OBJ, USD, STL, PLY, Alembic, `.blend`), and safe RNA introspection.
- **Declarative Bidirectional Nodes DSL:** build (`build_node_tree`), serialize (`get_node_tree`), and incrementally patch (`patch_node_tree`) **Shader**, **World**, **Geometry Nodes**, and **Compositor** graphs with topological auto-layout and live socket introspection (`list_node_types`).
- **Native Visual Feedback Loop:** `capture_viewport`, labeled 2×2 `capture_multiview` contact sheets, and `render_preview` returning inline PNG images directly to multimodal agents.
- **Asynchronous Jobs with Progress & Cancellation:** animation rendering, still renders, and physics bakes run cooperatively on Blender's main thread, streaming real-time MCP progress notifications and supporting instant between-frame cancellation.
- **Complete MCP Platform (SDK v2):** live Resources with real-time subscriptions (`depsgraph_update_post` with debounce), 7 guided workflow Prompts, live Completions, **Dynamic Toolsets** (`tools/list_changed`) for clients with tool-count caps, simultaneous multi-instance Blender control, and hardened **Streamable HTTP** (DNS rebinding protection + optional Bearer authentication).
- **External Integrations v1 + Plugins:** **Poly Haven** and **ambientCG** (CC0, zero API key required), **Sketchfab**, unified **`AI3DProvider`** interface (**Hyper3D Rodin**, **Hunyuan3D** cloud or local self-hosted, **Tripo3D**, **Meshy**, **TRELLIS**) with a Zip-Slip-safe local asset cache, plus third-party extensibility via Python entry points (`blender_mcp.plugins`).
- **Secure by Default:** binds exclusively to `127.0.0.1`, 256-bit random session token, `BLENDER_MCP_ALLOW_PYTHON=false` by default (`false` / `confirm` / `true`), directory allowlist (`BLENDER_MCP_ALLOWED_DIRS`), named scene checkpoints, and JSONL audit logging.

## Architecture & Licensing

Two cleanly separated processes communicating via **length-prefixed JSON-RPC 2.0 over localhost TCP**:

- **`packages/server`** *(MIT)* — External MCP server in Python ≥ 3.11 (`MCPServer` v2, external integrations, visual compositing, security guards, CLI).
- **`packages/protocol`** *(MIT)* — Shared framing, structured error codes, and message types (stdlib-only).
- **`packages/addon`** *(GPL-3.0-or-later)* — In-Blender bridge (stdlib-only Python ≥ 3.10), dual packaging (**Blender 4.2+ Extension** and **3.6–4.1 legacy Add-on**), and feature-detection `compat/` layer spanning Blender 3.6 LTS → 5.3+.

See [LICENSING.md](LICENSING.md) for details on the hybrid MIT + GPL-3.0-or-later licensing structure.

## Quick Start

```bash
# 1. Clone the repository and enter the blender server directory
git clone https://github.com/antonyguedes/mcp-servers.git
cd mcp-servers/blender

# 2. Install workspace dependencies
uv sync --group dev

# 3. Install the bridge add-on into Blender (auto-detects 4.2+ Extension or 3.6-4.1 legacy Add-on)
uv run blender-mcp install-addon

# 4. Verify your Blender installation and bridge connection
uv run blender-mcp doctor
```

Or launch Blender **headless** (no GUI required):
```bash
uv run blender-mcp launch --port 9876
```

Or run via **headless Docker** (Blender + Streamable HTTP server):
```bash
docker compose -f docker/docker-compose.yml up --build
```

## Example — Declarative Nodes DSL

```json
{
  "tree": "material:BrushedGold",
  "nodes": {
    "noise": {"type": "ShaderNodeTexNoise", "inputs": {"Scale": 40, "Detail": 8}},
    "ramp":  {"type": "ShaderNodeValToRGB", "props": {"color_ramp.elements": [[0.35, [0.18,0.18,0.18,1]], [0.65, [0.45,0.45,0.45,1]]]}},
    "bsdf":  {"type": "ShaderNodeBsdfPrincipled", "inputs": {"Base Color": [1.0, 0.77, 0.34, 1], "Metallic": 1.0}}
  },
  "links": [["noise.Fac", "ramp.Fac"], ["ramp.Color", "bsdf.Roughness"], ["bsdf.BSDF", "output.Surface"]],
  "layout": "auto"
}
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BLENDER_MCP_ALLOW_PYTHON` | `false` | Controls `execute_python` / `run_script_file`: `false`, `confirm`, or `true` |
| `BLENDER_MCP_PYTHON_TIMEOUT` | `30` | Maximum execution timeout (seconds) for Python scripts |
| `BLENDER_MCP_PROFILE` | `modeling` | Initial toolset profile: `minimal`, `modeling`, `animation`, `integrations`, or `full` |
| `BLENDER_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` or `http` (`streamable-http`) |
| `BLENDER_MCP_HTTP_HOST` / `PORT` | `127.0.0.1` / `8765` | Bind host and port for Streamable HTTP transport |
| `BLENDER_MCP_HTTP_BEARER_TOKEN` | *(empty)* | Requires `Authorization: Bearer <token>` on HTTP requests when set |
| `BLENDER_MCP_ALLOWED_DIRS` | *(unrestricted)* | Allowlist of directories for file I/O (`:` on Linux/macOS, `;` on Windows) |
| `BLENDER_MCP_CACHE_DIR` | `~/.cache/blender-mcp/assets` | Local cache directory for downloaded external assets |
| `BLENDER_MCP_AUDIT_LOG` | `~/.local/state/blender-mcp/audit.jsonl` | JSONL audit log for mutating calls (`off` disables logging) |
| `BLENDER_MCP_BLENDER_PATH` | *(auto)* | Explicit path to the Blender executable |
| `SKETCHFAB_API_KEY` | *(empty)* | Enables Sketchfab model downloads |
| `HYPER3D_API_KEY` | *(empty)* | Enables Hyper3D Rodin 3D generation |
| `HUNYUAN3D_API_KEY` / `HUNYUAN3D_BASE_URL` | *(empty)* | Enables Hunyuan3D (cloud API or local self-hosted server) |
| `TRIPO_API_KEY` / `MESHY_API_KEY` / `TRELLIS_BASE_URL` | *(empty)* | Enables Tripo3D, Meshy, or local TRELLIS generation |

## Documentation

- [docs/CLIENTS.md](docs/CLIENTS.md) — Ready-to-use snippets and verification checklist for 9 MCP clients + HTTP/Docker
- [docs/TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) — Complete auto-generated reference of all tools, resources, and prompts
- [docs/PLUGINS.md](docs/PLUGINS.md) — How to build third-party plugins and custom AI 3D providers via `blender_mcp.plugins`
- [LICENSING.md](LICENSING.md) — Hybrid MIT + GPL-3.0-or-later licensing details

## Testing, Evals & Benchmarks

```bash
# Lint, typecheck, unit tests, and security audit
uv run ruff check .
uv run pyright
uv run pytest tests/unit -v

# End-to-end integration tests, agent eval suite, and latency benchmarks on headless Blender
uv run pytest tests/integration tests/evals tests/benchmarks -m integration -v

# Regenerate schema reference documentation
uv run python scripts/generate_docs.py
```
