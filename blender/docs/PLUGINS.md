# Plugin Authoring Guide — `blender-mcp`

`blender-mcp` supports third-party extensions through **Python Entry Points** under the `blender_mcp.plugins` group, letting external packages register custom MCP tools, Resources, Prompts, or new AI 3D generation providers (`AI3DProvider`) without modifying core code.

## 1. Declare the Entry Point in Your Package's `pyproject.toml`

```toml
[project]
name = "my-blender-mcp-plugin"
version = "0.1.0"
dependencies = ["blender-mcp>=1.0.0"]

[project.entry-points."blender_mcp.plugins"]
my_plugin = "my_blender_mcp_plugin:register"
```

## 2. Implement `register(ctx: PluginContext)`

```python
from pathlib import Path
from blender_mcp.integrations.ai3d import AI3DProvider
from blender_mcp.plugins import PluginContext


class MyCustom3DProvider(AI3DProvider):
    name = "my_3d_provider"
    env_hint = "MY_3D_API_KEY"

    def is_configured(self) -> bool:
        return True

    async def generate(self, *, prompt, image_path, output_dir: Path, cache, on_progress=None, **kwargs) -> Path:
        # Generate or download a .glb model into output_dir / "model.glb"
        dest = output_dir / "model.glb"
        ...
        return dest


def register(ctx: PluginContext) -> None:
    # 1. Register a custom AI 3D provider
    ctx.integrations.ai3d.register(MyCustom3DProvider())

    # 2. Register custom MCP tools
    @ctx.mcp.tool()
    async def inspect_custom_asset(object_name: str) -> dict:
        """Example plugin tool calling the live Blender bridge."""
        return await ctx.runtime.invoke("core.get_object_details", {"object": object_name})
```

## 3. Available Properties on `PluginContext`

| Attribute | Purpose |
|---|---|
| `ctx.mcp` | The `MCPServer` instance for registering tools, resources, and prompts |
| `ctx.runtime` | `ToolRuntime` providing `invoke(method, params)`, `bridge`, `pool`, `settings`, and `path_guard` |
| `ctx.integrations` | `IntegrationsHub` exposing `cache`, `polyhaven`, `ambientcg`, `sketchfab`, and `ai3d` |
| `ctx.toolsets` | `ToolsetManager` for inspecting or dynamically managing toolsets |
