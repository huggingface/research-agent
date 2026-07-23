from __future__ import annotations

import pytest

from fast_agent import AgentAuth
from fastmcp import FastMCPApp
from research.app_auth import effective_agent_auth
from research.fastmcp_server import (
    PRODUCTION_UI_DESIGN,
    build_fast_agent,
    configure_research_ui_csp,
    enforce_production_isolation,
)
from research.hf_design import HF_RESOURCE_DOMAINS


@pytest.mark.asyncio
async def test_production_harness_disables_model_visible_host_shell() -> None:
    fast = build_fast_agent()

    async with fast.harness():
        enforce_production_isolation(fast)

        assert fast.app.context.no_shell
        assert not fast.app.context.config.mcp.servers["hf"].include_instructions


def test_explicit_caller_auth_is_preserved_for_agent_initialization() -> None:
    auth = AgentAuth.bearer("caller-token", provider="huggingface", subject="alice")

    assert effective_agent_auth(auth) is auth


def test_production_uses_hub_classic_design() -> None:
    assert PRODUCTION_UI_DESIGN == "hub-classic"


@pytest.mark.asyncio
async def test_research_ui_csp_allows_google_font_resources() -> None:
    app = FastMCPApp("test")

    @app.ui(name="research")
    def research() -> dict[str, str]:
        return {"status": "ok"}

    configure_research_ui_csp(app)
    tool = await app.get_tool("research")

    assert tool is not None
    assert tool.meta["ui"]["csp"]["resourceDomains"] == list(HF_RESOURCE_DOMAINS)
