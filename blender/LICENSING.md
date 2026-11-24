# Licensing — `blender-mcp`

This project uses a **hybrid licensing model** to fully comply with Blender Foundation's GNU GPL policy while preserving maximum permissive adoption for the external MCP server and the broader `mcp-servers/` monorepo.

| Component | Path | License | Rationale |
|---|---|---|---|
| **MCP Server** | `packages/server/` | **MIT** | Standalone external process communicating with Blender solely over a local TCP JSON-RPC protocol |
| **Shared Protocol** | `packages/protocol/` | **MIT** | Wire framing, error codes, and message types with zero `bpy` dependency |
| **Docs, Tests & Configs** | `docs/`, `tests/`, `docker/`, `scripts/` | **MIT** | Freely reusable across community and commercial projects |
| **Blender Add-on / Extension** | `packages/addon/` | **GPL-3.0-or-later** | Executes inside Blender's process and imports `bpy`, requiring a GNU GPL v3+ compatible license |

## License Compatibility

The **MIT** license is permissive and 100% compatible with **GPL-3.0-or-later**. The boundary between the external MCP server and the Blender add-on is a clean process boundary (IPC over localhost TCP using JSON-RPC 2.0).

See:
- [LICENSE](LICENSE) (MIT)
- [packages/addon/LICENSE](packages/addon/LICENSE) (GNU GPL-3.0-or-later)
