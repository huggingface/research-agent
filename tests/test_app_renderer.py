from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP
from fastmcp.apps import FastMCPApp
from fastmcp.server.providers.addressing import hash_tool
from prefab_ui.app import PrefabApp
from prefab_ui.components import Heading

from research.app_renderer import (
    PREFAB_OUTPUT_SCHEMA,
    _with_chatgpt_remount_recovery,
    install_versioned_renderer,
)


def test_remount_recovery_leaves_bundled_renderer_unchanged() -> None:
    html = '<script type="module" crossorigin>console.log("bundled")</script>'

    assert _with_chatgpt_remount_recovery(html) == html


@pytest.mark.asyncio
async def test_renderer_uri_is_content_addressed_and_readable() -> None:
    mcp = FastMCP("test")
    app = FastMCPApp("Hugging Face Researcher")

    @app.ui(name="researcher")
    def researcher() -> PrefabApp:
        return PrefabApp(
            view=Heading("Research"),
            state={"job": {"headline": "Research"}},
        )

    mcp.add_provider(app)
    digest = install_versioned_renderer(
        mcp,
        app_name="Hugging Face Researcher",
        tool_name="researcher",
        build_id="a1b2c3d4",
        resource_domains=(
            "https://fonts.googleapis.com",
            "https://fonts.gstatic.com",
        ),
        widget_domain="https://researcher.example",
    )

    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools if tool.name == "researcher")
        uri = tool.meta["ui"]["resourceUri"]
        result = await client.call_tool("researcher", {})
        contents = await client.read_resource(uri)
        resources = await client.list_resources()

    tool_digest = hash_tool("Hugging Face Researcher", "researcher")
    assert uri == (f"ui://prefab/tool/{tool_digest}/renderer-{digest}.html")
    assert tool.outputSchema == PREFAB_OUTPUT_SCHEMA
    assert not any(key.startswith("openai/") for key in tool.meta)
    assert tool.meta["ui/resourceUri"] == uri
    assert result.structured_content is not None
    assert {"$prefab", "view", "state"} <= result.structured_content.keys()
    assert contents[0].mimeType == "text/html;profile=mcp-app"
    html = contents[0].text
    assert "@prefecthq/prefab-ui@0.20.2" in html
    assert 'content="a1b2c3d4"' in html
    assert "window.openai?.toolOutput" in html
    assert 'window.addEventListener("openai:set_globals"' in html
    assert "setTimeout(stopRecovery, 30000)" in html
    assert "event.stopImmediatePropagation()" in html
    assert "ignored non-Prefab tool-result notification" in html
    assert 'typeof value.state.job_id === "string"' in html
    assert "window.openai?.widgetState" in html
    assert "window.openai?.setWidgetState" in html
    assert "hydrated from direct status endpoint" in html
    assert 'method: "ui/notifications/tool-result"' in html
    assert "params: { structuredContent: output }" in html
    assert "localStorage" not in html
    resource = next(resource for resource in resources if str(resource.uri) == uri)
    assert resource.meta["ui"]["csp"]["resourceDomains"] == [
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
    ]
    assert resource.meta["ui"]["csp"]["connectDomains"] == [
        "https://researcher.example"
    ]
    assert resource.meta["ui"]["domain"] == "https://researcher.example"
    assert resource.meta["ui"]["prefersBorder"] is True
    assert not any(key.startswith("openai/") for key in resource.meta)
