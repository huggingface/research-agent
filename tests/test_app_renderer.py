from __future__ import annotations

import pytest

from fastmcp import Client, FastMCP
from fastmcp.apps import FastMCPApp
from fastmcp.server.providers.addressing import hash_tool
from prefab_ui.app import PrefabApp
from prefab_ui.components import Heading

from research.app_renderer import install_versioned_renderer


@pytest.mark.asyncio
async def test_renderer_uri_is_content_addressed_and_readable() -> None:
    mcp = FastMCP("test")
    app = FastMCPApp("Hugging Face Researcher")

    @app.ui(name="researcher")
    def researcher() -> PrefabApp:
        return PrefabApp(view=Heading("Research"))

    mcp.add_provider(app)
    digest = install_versioned_renderer(
        mcp,
        app_name="Hugging Face Researcher",
        tool_name="researcher",
        build_id="a1b2c3d4",
    )

    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools if tool.name == "researcher")
        uri = tool.meta["ui"]["resourceUri"]
        contents = await client.read_resource(uri)

    tool_digest = hash_tool("Hugging Face Researcher", "researcher")
    assert uri == (f"ui://prefab/tool/{tool_digest}/renderer-{digest}.html")
    assert contents[0].mimeType == "text/html;profile=mcp-app"
    assert "@prefecthq/prefab-ui@0.20.2" in contents[0].text
    assert 'content="a1b2c3d4"' in contents[0].text
