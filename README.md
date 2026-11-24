<div align="center">

<img src="./docs/assets/hero-banner.svg" alt="mcp-servers — Production-grade MCP servers connecting AI agents to desktop and creative software" width="100%" />

<br />

[![Protocol: MCP](https://img.shields.io/badge/Protocol-MCP-38bdf8?style=for-the-badge&logo=json&logoColor=38bdf8&labelColor=0c1426)](https://modelcontextprotocol.io/)
[![Servers: 1 Ready](https://img.shields.io/badge/Servers-1_Ready-818cf8?style=for-the-badge&logo=stackblitz&logoColor=818cf8&labelColor=0c1426)](#-available-servers)
[![Transports](https://img.shields.io/badge/Transports-stdio_·_Streamable_HTTP-34d399?style=for-the-badge&logo=fastapi&logoColor=34d399&labelColor=0c1426)](#-architecture)
[![Blender 3.6–5.3+](https://img.shields.io/badge/Blender-3.6_LTS_%E2%86%92_5.3%2B-fb923c?style=for-the-badge&logo=blender&logoColor=fb923c&labelColor=0c1426)](./blender/README.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-c084fc?style=for-the-badge&logo=opensourceinitiative&logoColor=f4f7ff&labelColor=0c1426)](./LICENSE)

<p align="center">
  <strong>A curated collection of standalone Model Context Protocol (MCP) servers for desktop and creative software.</strong><br />
  <em>Give AI agents from Claude, Cursor, VS Code Copilot, Gemini CLI, Antigravity, Windsurf, Codex, or Zed direct, semantic control over real tools.</em>
</p>

<p align="center">
  <a href="#-available-servers">Servers</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-repository-structure">Structure</a> ·
  <a href="#-license">License</a>
</p>

</div>

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## ✨ Overview

**`mcp-servers`** is a monorepo hosting independent, production-grade **Model Context Protocol (MCP)** servers so AI agents can operate third-party software reliably — beyond fragile UI clicking or unrestricted arbitrary scripts.

| Principle | How it is applied across servers |
| :--- | :--- |
| 🧩 **Standalone & Modular** | Each server lives in its own top-level folder with independent dependencies, tests, CI workflow, and dedicated documentation. |
| 🎯 **Semantic Over Raw Scripting** | High-level typed tools, structured diffs, resources, and visual feedback loops instead of brittle ad-hoc code injection. |
| 🔒 **Secure by Default** | Localhost-only bridges, session authentication, directory allowlists, audit trails, and explicit opt-in gates for risky actions. |

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## 🔌 Available Servers

Each server maintains its own `README.md`, installation steps, client configuration snippets, and tool reference.

| Server | Target Software | Highlights | Runtime & Transport | License | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| [**`blender/`**](./blender/README.md) | **Blender 3D** (`3.6 LTS → 5.3+`) | 128 semantic tools across 19 toolsets, declarative Nodes DSL, visual viewport feedback, async jobs, dynamic toolsets, multi-instance control, Poly Haven / ambientCG / Sketchfab / AI 3D integrations & plugin system · [Clients](./blender/docs/CLIENTS.md) · [Tools](./blender/docs/TOOLS_REFERENCE.md) · [Plugins](./blender/docs/PLUGINS.md) | Python (`uv`) · `stdio`, Streamable HTTP, Docker | `MIT` + `GPL-3.0-or-later` *(add-on)* | ✅ `v1.0` |

> [!NOTE]
> More MCP servers for additional desktop, creative, and engineering applications are planned and will be added as standalone directories in this repository.

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## 🧠 Architecture

Every server follows a clean process separation between the **MCP Server** (talking standard MCP to any agent client) and a lightweight **local bridge / adapter** inside or alongside the target software:

```mermaid
%%{init: {"theme": "base", "themeVariables": {"primaryColor": "#131f3a", "primaryTextColor": "#f4f7ff", "primaryBorderColor": "#818cf8", "lineColor": "#64748b", "secondaryColor": "#0d172e", "tertiaryColor": "#0c1426", "fontFamily": "Inter, Segoe UI, Roboto, sans-serif"}}}%%
flowchart LR
    CLIENTS["🤖 MCP Clients<br/>Claude · Cursor · Copilot<br/>Gemini CLI · Antigravity · Zed"]
    MCP["🔌 MCP Server<br/>stdio / Streamable HTTP"]
    BRIDGE["🌉 Local Bridge / IPC<br/>127.0.0.1 · Auth Token"]
    APP["🎨 Target Software<br/>Blender 3D · More soon"]

    CLIENTS <-->|"MCP (JSON-RPC)"| MCP
    MCP <-->|"Local RPC"| BRIDGE
    BRIDGE <-->|"Native API"| APP

    style CLIENTS fill:#0d172e,stroke:#38bdf8,stroke-width:1.8px,color:#f4f7ff
    style MCP fill:#131f3a,stroke:#818cf8,stroke-width:2px,color:#f4f7ff
    style BRIDGE fill:#0d172e,stroke:#34d399,stroke-width:1.8px,color:#f4f7ff
    style APP fill:#131f3a,stroke:#fb923c,stroke-width:2px,color:#f4f7ff
```

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## 🚀 Quick Start

Clone the repository and navigate to the server you want to use:

```bash
git clone https://github.com/antonyguedes/mcp-servers.git
cd mcp-servers
```

Then follow the setup guide inside the target server's directory:

- **Blender 3D:** see [`blender/README.md`](./blender/README.md) and [`blender/docs/CLIENTS.md`](./blender/docs/CLIENTS.md)

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## 📁 Repository Structure

```text
mcp-servers/
├── .github/workflows/       # Per-server GitHub Actions CI workflows
├── docs/assets/             # Shared visual assets (banner & dividers)
├── blender/                 # blender-mcp v1.0 (MCP server + protocol + Blender add-on)
│   ├── README.md            # Full documentation, quick start & env vars
│   ├── docs/                # Client configs, auto-generated tool reference & plugin guide
│   ├── packages/            # server (MIT), protocol (MIT), addon (GPL-3.0-or-later)
│   ├── docker/              # Headless Blender + Streamable HTTP container
│   └── tests/               # Unit, security audit, E2E integration, evals & benchmarks
├── LICENSE                  # Root MIT License
└── README.md                # You are here
```

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

## 📄 License

This repository is distributed under the [MIT License](./LICENSE). © 2026 Antony Guedes.

Individual sub-components that integrate directly with copyleft software APIs carry their own license inside their respective folder (for example, [`blender/packages/addon/`](./blender/packages/addon/LICENSE) is licensed under `GPL-3.0-or-later` — see [`blender/LICENSING.md`](./blender/LICENSING.md) for details).

<img src="./docs/assets/accent-line.svg" alt="" width="100%" />

<div align="center">
  <sub>Built for reliable, secure, agent-native workflows across desktop and creative software.</sub>
</div>
