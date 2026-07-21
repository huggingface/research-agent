"""Versioned Prefab renderer resource for reliable host cache invalidation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from fastmcp import FastMCP
from fastmcp.apps.config import UI_MIME_TYPE, AppConfig, ResourceCSP
from fastmcp.server.providers.addressing import hash_tool
from fastmcp.server.transforms import Transform
from fastmcp.tools.base import Tool
from prefab_ui.renderer import get_renderer_csp, get_renderer_html


class RendererUriTransform(Transform):
    """Point one UI tool at a content-addressed renderer resource."""

    def __init__(self, tool_name: str, resource_uri: str) -> None:
        self.tool_name = tool_name
        self.resource_uri = resource_uri

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [
            self._with_renderer(tool) if tool.name == self.tool_name else tool
            for tool in tools
        ]

    def _with_renderer(self, tool: Tool) -> Tool:
        meta = dict(tool.meta or {})
        ui = dict(meta.get("ui") or {})
        ui["resourceUri"] = self.resource_uri
        meta["ui"] = ui
        return tool.model_copy(update={"meta": meta})


def install_versioned_renderer(
    mcp: FastMCP,
    *,
    app_name: str,
    tool_name: str,
    build_id: str,
) -> str:
    """Register the Prefab renderer at a URI derived from its exact content."""
    html = get_renderer_html().replace(
        "</head>",
        f'<meta name="research-app-build" content="{build_id}"></head>',
    )
    digest = hashlib.sha256(html.encode()).hexdigest()[:12]
    tool_digest = hash_tool(app_name, tool_name)
    resource_uri = f"ui://prefab/tool/{tool_digest}/renderer-{digest}.html"
    csp = ResourceCSP(**(get_renderer_csp() or {}))

    @mcp.resource(
        resource_uri,
        name="Versioned Prefab Renderer",
        mime_type=UI_MIME_TYPE,
        app=AppConfig(csp=csp),
    )
    def prefab_renderer() -> str:
        return html

    mcp.add_transform(RendererUriTransform(tool_name, resource_uri))
    return digest


def app_build_id(home: Path) -> str:
    """Hash the app code and prompts that shape a rendered research view."""
    digest = hashlib.sha256()
    paths = sorted(home.glob("*.py")) + sorted((home / "agent-cards").glob("*.md"))
    for path in paths:
        digest.update(path.relative_to(home).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:8]
