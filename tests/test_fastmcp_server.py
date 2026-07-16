from __future__ import annotations

import pytest

from fast_agent import AgentAuth
from research.app_auth import effective_agent_auth
from research.fastmcp_server import build_fast_agent, enforce_production_isolation


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
