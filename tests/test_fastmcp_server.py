from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fast_agent import AgentAuth
from fastmcp import Client, FastMCP, FastMCPApp
from starlette.requests import Request
from starlette.responses import Response

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
    McpBrowserRedirectMiddleware,
    _connection_url,
    register_landing_page,
)
from research.status_capability import StatusCapabilityStore
from research.widget_status import register_widget_status_route


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
    assert "data:image/svg+xml;base64," in landing.text
    assert "🤗" not in landing.text
    assert "script-src 'unsafe-inline'" in LANDING_PAGE_CSP
    assert landing.headers["content-security-policy"] == LANDING_PAGE_CSP
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)


@pytest.mark.asyncio
async def test_browser_get_on_mcp_redirects_without_claiming_sse() -> None:
    mcp = FastMCP("landing-test")
    register_landing_page(mcp)
    app = McpBrowserRedirectMiddleware(
        mcp.http_app(path="/mcp", transport="http", stateless_http=True)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://researcher.example",
        follow_redirects=False,
    ) as client:
        browser = await client.get("/mcp", headers={"Accept": "text/html"})
        query = await client.get("/mcp?source=browser")
        sse = await client.get("/mcp", headers={"Accept": "text/event-stream"})

    for response in (browser, query):
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["vary"] == "Accept"
    assert sse.status_code == 405


@pytest.mark.asyncio
async def test_zero_quality_sse_accept_redirects_to_welcome_page() -> None:
    async def downstream(scope, receive, send) -> None:
        response = Response("protocol", status_code=418)
        await response(scope, receive, send)

    app = McpBrowserRedirectMiddleware(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://researcher.example",
        follow_redirects=False,
    ) as client:
        rejected = await client.get(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream;q=0"},
        )
        protocol = await client.get(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream;q=0.9"},
        )
        invalid = await client.get(
            "/mcp",
            headers={"Accept": "text/event-stream;q=2"},
        )
        post = await client.post("/mcp")

    assert rejected.status_code == 303
    assert protocol.status_code == 418
    assert invalid.status_code == 303
    assert post.status_code == 418


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


@pytest.mark.asyncio
async def test_researcher_uses_client_only_direct_status_capability() -> None:
    mcp = FastMCP("test")
    app = FastMCPApp("Hugging Face Researcher")
    jobs = ResearchJobStore()
    capabilities = StatusCapabilityStore()
    register_research_app(
        app,
        jobs=jobs,
        runner=RunnerSimulator(),  # type: ignore[arg-type]
        build_id="build",
        status_capabilities=capabilities,
        status_origin="https://researcher.example",
    )
    mcp.add_provider(app)

    async with Client(mcp) as client:
        result = await client.call_tool("researcher", {"topic": "Test direct status"})

    assert result.meta is not None
    assert result.meta["research"]["statusUrl"].startswith(
        "https://researcher.example/widget/research/"
    )
    assert "view=1" in result.meta["research"]["recoveryUrl"]
    assert result.structured_content is not None
    assert result.structured_content["state"]["status_url"] == ""
    assert "widget/research" not in str(result.structured_content)
    assert '"action": "fetch"' in json.dumps(result.structured_content["view"])


@pytest.mark.asyncio
async def test_direct_status_route_authorizes_snapshot_and_recovery_view() -> None:
    mcp = FastMCP("test")
    jobs = ResearchJobStore()
    capabilities = StatusCapabilityStore()
    job = await jobs.create("Test direct status", "owner")
    job.markdown_report_blocks = [{"type": "markdown", "text": "# Findings"}]
    job.markdown_report_revision = 1
    token = capabilities.issue(job.id, job.owner_id)
    register_widget_status_route(
        mcp,
        jobs=jobs,
        capabilities=capabilities,
        build_id="build",
        origin="https://researcher.example",
        design=PRODUCTION_UI_DESIGN,
    )
    app = mcp.http_app(path="/mcp", transport="http", stateless_http=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://researcher.example",
    ) as client:
        status = await client.get(f"/widget/research/{token}")
        recovery = await client.get(f"/widget/research/{token}?view=1")
        invalid = await client.get(f"/widget/research/{token}x")
        options = await client.options(f"/widget/research/{token}")

    assert status.status_code == 200
    assert status.json()["job_id"] == job.id
    assert status.json()["report_ready"] is True
    assert status.json()["report_blocks"] == job.markdown_report_blocks
    assert "owner_id" not in status.text
    assert status.headers["cache-control"] == "no-store"
    assert status.headers["access-control-allow-origin"] == "*"
    assert {"$prefab", "view", "state"} <= recovery.json().keys()
    assert recovery.json()["state"]["status_url"].endswith(token)
    assert recovery.json()["state"]["report_blocks"] == job.markdown_report_blocks
    assert recovery.json()["state"]["report_loaded"] is True
    assert invalid.status_code == 404
    assert options.status_code == 204


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
