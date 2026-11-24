# SPDX-License-Identifier: MIT
"""Auto-generate docs/TOOLS_REFERENCE.md from live MCPServer schemas, Resources, and Prompts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy


def _format_params(schema: dict[str, Any]) -> str:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not props:
        return "_None_"
    items: list[str] = []
    for name, meta in props.items():
        typ = meta.get("type")
        if not typ and "anyOf" in meta:
            typ = " \\| ".join(str(x.get("type", "any")) for x in meta["anyOf"])
        if not typ and "enum" in meta:
            typ = "enum"
        req = " *(required)*" if name in required else ""
        items.append(f"`{name}` (`{typ or 'any'}`){req}")
    return ", ".join(items)


def _format_badges(annotations: Any) -> str:
    if annotations is None:
        return ""
    badges: list[str] = []
    if getattr(annotations, "read_only_hint", False):
        badges.append("`read-only`")
    if getattr(annotations, "destructive_hint", False):
        badges.append("`destructive`")
    if getattr(annotations, "idempotent_hint", False) and not getattr(annotations, "read_only_hint", False):
        badges.append("`idempotent`")
    return " ".join(badges)


async def generate_reference_markdown() -> str:
    settings = ServerSettings(
        profile="full",
        python_policy=PythonPolicy.TRUE,
        audit_log=None,
    )
    mcp = create_server(settings, discover_plugins=False)
    toolsets = mcp._blender_toolsets  # type: ignore[attr-defined]
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    templates = await mcp.list_resource_templates()
    prompts = await mcp.list_prompts()

    tool_by_name = {t.name: t for t in tools}

    lines: list[str] = [
        "# `blender-mcp` — Complete Schema Reference",
        "",
        "> Auto-generated from live `MCPServer` schemas via `uv run python scripts/generate_docs.py`.",
        "",
        f"- **Total tools (`full` profile + scripting):** `{len(tools)}`",
        f"- **Toolsets:** `{len(toolsets.catalog)}` (+ dynamic toolset & multi-instance management tools)",
        f"- **Resources:** `{len(resources)}` static + `{len(templates)}` templates",
        f"- **Guided Prompts:** `{len(prompts)}`",
        "",
        "---",
        "",
        "## Tools by Toolset",
        "",
    ]

    assigned: set[str] = set()
    for row in toolsets.status():
        ts_name = row["name"]
        names = sorted(toolsets._tool_names_by_set.get(ts_name, []))
        assigned.update(names)
        lines.append(f"### `{ts_name}` — {row['description']} ({len(names)} tools)")
        lines.append("")
        lines.append("| Tool | Flags | Description | Parameters |")
        lines.append("|---|---|---|---|")
        for tn in names:
            t = tool_by_name.get(tn)
            if t is None:
                continue
            desc = (t.description or "").strip().splitlines()[0].replace("|", "\\|")
            badges = _format_badges(t.annotations)
            params = _format_params(t.input_schema or {})
            lines.append(f"| `{t.name}` | {badges} | {desc} | {params} |")
        lines.append("")

    meta_tools = sorted(set(tool_by_name.keys()) - assigned)
    if meta_tools:
        lines.append(f"### `platform` — Dynamic Toolsets & Multi-Instance Management ({len(meta_tools)} tools)")
        lines.append("")
        lines.append("| Tool | Flags | Description | Parameters |")
        lines.append("|---|---|---|---|")
        for tn in meta_tools:
            t = tool_by_name[tn]
            desc = (t.description or "").strip().splitlines()[0].replace("|", "\\|")
            badges = _format_badges(t.annotations)
            params = _format_params(t.input_schema or {})
            lines.append(f"| `{t.name}` | {badges} | {desc} | {params} |")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Resources & Resource Templates",
            "",
            "| URI | MIME Type | Description |",
            "|---|---|---|",
        ]
    )
    for r in resources:
        desc = (r.description or "").replace("|", "\\|")
        lines.append(f"| `{r.uri}` | `{r.mime_type}` | {desc} |")
    for tmpl in templates:
        desc = (tmpl.description or "").replace("|", "\\|")
        lines.append(f"| `{tmpl.uri_template}` | `{tmpl.mime_type}` | {desc} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## Guided Prompts",
            "",
            "| Prompt | Description | Arguments |",
            "|---|---|---|",
        ]
    )
    for p in prompts:
        args = ", ".join(f"`{a.name}`" for a in (p.arguments or [])) or "_None_"
        desc = (p.description or "").replace("|", "\\|")
        lines.append(f"| `{p.name}` | {desc} | {args} |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "docs" / "TOOLS_REFERENCE.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md = asyncio.run(generate_reference_markdown())
    out_path.write_text(md, encoding="utf-8")
    print(f"Generated {out_path} ({len(md)} bytes)")


if __name__ == "__main__":
    main()
