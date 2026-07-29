from __future__ import annotations

import asyncio

import httpx
import pytest
from fast_agent import AgentAuth
from fastmcp import Client, FastMCP, FastMCPApp
from starlette.requests import Request

from research.app_auth import effective_agent_auth
from research.app_jobs import ResearchJobStore
from research.fastmcp_server import (
    PRODUCTION_UI_DESIGN,
    build_fast_agent,
    configure_research_ui_csp,
    enforce_production_isolation,
    register_research_app,
    use_stateless_http,
)
from research.hf_design import HF_RESOURCE_DOMAINS
from research.landing_page import (
    LANDING_PAGE_CSP,
    _connection_url,
    register_landing_page,
)


class RunnerSimulator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.job = None

    async def run(self, job, auth) -> None:
        self.job = job
        self.started.set()


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
async def test_public_landing_page_shows_request_specific_mcp_url() -> None:
    mcp = FastMCP("researcher")
    register_landing_page(mcp)
    app = mcp.http_app(path="/mcp", transport="http", stateless_http=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://researcher.example",
    ) as client:
        landing = await client.get("/")

    assert landing.status_code == 200
    assert landing.headers["content-type"].startswith("text/html")
    assert "Hugging Face Research MCP Server" in landing.text
    assert "https://researcher.example/mcp" in landing.text
    assert 'id="copy-url"' in landing.text
    assert "navigator.clipboard.writeText" in landing.text
    assert "https://huggingface.co/spaces/evalstate/researcher-reports" in landing.text
    assert "script-src 'unsafe-inline'" in LANDING_PAGE_CSP
    assert landing.headers["content-security-policy"] == LANDING_PAGE_CSP
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)


def test_landing_page_prefers_public_hugging_face_space_host() -> None:
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("internal", 80),
            "path": "/",
            "headers": [],
        }
    )

    assert _connection_url(request, "evalstate-researcher.hf.space") == (
        "https://evalstate-researcher.hf.space/mcp"
    )


@pytest.mark.asyncio
async def test_public_tool_is_hugging_face_researcher() -> None:
    app = FastMCPApp("test")

    register_research_app(
        app,
        jobs=object(),  # type: ignore[arg-type]
        runner=object(),  # type: ignore[arg-type]
        build_id="build",
    )

    tool = await app.get_tool("researcher")
    assert tool is not None
    assert tool.title == "Hugging Face Researcher"
    assert await app.get_tool("research") is None


@pytest.mark.asyncio
async def test_researcher_starts_work_before_returning_ui() -> None:
    mcp = FastMCP("test")
    app = FastMCPApp("test")
    jobs = ResearchJobStore()
    runner = RunnerSimulator()
    register_research_app(
        app,
        jobs=jobs,
        runner=runner,  # type: ignore[arg-type]
        build_id="build",
    )
    mcp.add_provider(app)

    async with Client(mcp) as client:
        await client.call_tool("researcher", {"topic": "Test the backend start"})
        await asyncio.wait_for(runner.started.wait(), timeout=1)

    assert runner.job is not None
    assert runner.job.status == "running"
    assert runner.job.phase == "researching"


@pytest.mark.parametrize("transport", ["http", "streamable-http"])
def test_production_http_avoids_restart_bound_session_state(transport: str) -> None:
    assert use_stateless_http(transport)


def test_legacy_sse_retains_required_session_state() -> None:
    assert not use_stateless_http("sse")


@pytest.mark.asyncio
async def test_research_ui_csp_allows_google_font_resources() -> None:
    app = FastMCPApp("test")

    @app.ui(name="researcher")
    def researcher() -> dict[str, str]:
        return {"status": "ok"}

    existing = await app.get_tool("researcher")
    assert existing is not None
    existing.meta.setdefault("ui", {})["csp"] = {
        "connectDomains": ["https://api.example.com"],
        "resourceDomains": ["https://assets.example.com"],
    }
    configure_research_ui_csp(app)
    tool = await app.get_tool("researcher")

    assert tool is not None
    assert tool.meta["ui"]["csp"] == {
        "connectDomains": ["https://api.example.com"],
        "resourceDomains": [
            "https://assets.example.com",
            *HF_RESOURCE_DOMAINS,
        ],
    }
