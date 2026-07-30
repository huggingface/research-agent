"""FastMCP App boundary for the Hugging Face Researcher."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Annotated, Any

from fast_agent import FastAgent
from fastmcp import Context as MCPContext
from fastmcp import FastMCP, FastMCPApp
from fastmcp.apps.app import _make_resolver
from fastmcp.tools import ToolResult
from pydantic import Field

from .app_artifacts import read_bucket_markdown
from .app_auth import auth_provider, http_middleware, request_auth
from .app_jobs import (
    ResearchJobStore,
    ResearchTaskRegistry,
    owner_id,
    unavailable_snapshot,
)
from .app_renderer import (
    app_build_id,
    default_widget_domain,
    install_versioned_renderer,
)
from .app_ui import build_research_ui
from .hf_design import HF_RESOURCE_DOMAINS, HFDesign
from .landing_page import register_landing_page
from .research_runner import ResearchRunner
from .status_capability import StatusCapabilityStore
from .widget_status import APP_NAME, capability_urls, register_widget_status_route

RESEARCH_HOME = Path(__file__).parent
AGENT_CARDS = RESEARCH_HOME / "agent-cards"
PRODUCTION_UI_DESIGN: HFDesign = "hub-classic"
STATELESS_TRANSPORTS = {"http", "streamable-http"}


def configure_research_ui_csp(
    app: FastMCPApp,
    tool_name: str = "researcher",
) -> None:
    """Allow the Google-hosted Hub fonts used by design variants."""
    for tool in app._local._components.values():
        if getattr(tool, "name", None) == tool_name:
            ui = tool.meta.setdefault("ui", {})
            csp = dict(ui.get("csp") or {})
            domains = list(csp.get("resourceDomains") or ())
            domains.extend(
                domain for domain in HF_RESOURCE_DOMAINS if domain not in domains
            )
            csp["resourceDomains"] = domains
            ui["csp"] = csp
            return
    raise RuntimeError(f"Prefab UI tool was not registered: {tool_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the research FastMCP App.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8724)
    parser.add_argument(
        "--transport",
        choices=("http", "streamable-http", "sse"),
        default="http",
    )
    return parser.parse_args()


def use_stateless_http(transport: str) -> bool:
    """Avoid stale in-memory MCP sessions on restartable HTTP deployments."""
    return transport in STATELESS_TRANSPORTS


def register_research_app(
    app: FastMCPApp,
    jobs: ResearchJobStore,
    runner: ResearchRunner,
    build_id: str,
    status_capabilities: StatusCapabilityStore | None = None,
    status_origin: str | None = None,
) -> None:
    """Register one UI entry point and its app-only backend tools."""
    tasks = ResearchTaskRegistry()

    @app.ui(
        name="researcher",
        title="Hugging Face Researcher",
        description=(
            "Conduct sourced research on Hugging Face. Provide specific, "
            "goal-focused requests or tasks that state what should be established, "
            "analysed, reproduced, or compared. State authoritative sources, "
            "timeframes, and constraints. Produces a comprehensive report with "
            "references, citations, and reproductions."
        ),
    )
    async def researcher(
        topic: Annotated[
            str,
            Field(
                description=(
                    "The clearly stated goal of the research or reproduction task. "
                    "Provide important constraints and the preferred approach when "
                    "specified. Work with the user to refine this before calling if needed. "
                )
            ),
        ],
        ctx: MCPContext,
    ) -> ToolResult:
        auth = request_auth()
        owner = owner_id(auth, ctx.session_id)
        job = await jobs.create(topic, owner)
        identity = (
            auth.subject or "authenticated user"
            if auth is not None
            else "local development user"
        )
        job.add_event(f"Workspace access confirmed for {identity}.", kind="Setup")
        result = await jobs.begin(job.id, owner)
        if result is not None and result.started:
            tasks.start(job.id, runner.run(job, auth))
        direct_status = status_capabilities is not None and status_origin is not None
        ui = build_research_ui(
            topic,
            job.snapshot(),
            build_id=build_id,
            design=PRODUCTION_UI_DESIGN,
            status_url="" if direct_status else None,
            recovery_url="" if direct_status else None,
        )
        meta = None
        if direct_status:
            token = status_capabilities.issue(job.id, owner)
            status_url, recovery_url = capability_urls(status_origin, token)
            meta = {
                "research": {
                    "statusUrl": status_url,
                    "recoveryUrl": recovery_url,
                }
            }
        return ToolResult(
            content="Research started. Open the interactive app for live progress.",
            structured_content=ui.to_json(tool_resolver=_make_resolver(APP_NAME)),
            meta=meta,
        )

    configure_research_ui_csp(app)

    @app.tool()
    async def research_status(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, Any]:
        auth = request_auth()
        job = await jobs.get(job_id, owner_id(auth, ctx.session_id))
        return job.snapshot() if job else unavailable_snapshot(job_id)

    @app.tool()
    async def research_report_preview(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, Any]:
        auth = request_auth()
        job = await jobs.get(job_id, owner_id(auth, ctx.session_id))
        if job is None or not job.markdown_report_uri:
            raise RuntimeError("Research Markdown report is not available yet")
        return {
            "blocks": job.markdown_report_blocks,
            "revision": job.markdown_report_revision,
        }

    @app.tool()
    async def cancel_research(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, Any]:
        auth = request_auth()
        result = await jobs.cancel(job_id, owner_id(auth, ctx.session_id))
        if result is None:
            return unavailable_snapshot(job_id)
        if result.cancel_task:
            tasks.cancel(job_id)
        return result.job.snapshot()

    @app.tool()
    async def research_chat_context(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, str]:
        auth = request_auth()
        job = await jobs.get(job_id, owner_id(auth, ctx.session_id))
        if job is None or not job.markdown_report_uri:
            raise RuntimeError("Research Markdown report is not available yet")
        markdown = await asyncio.to_thread(read_bucket_markdown, job, auth)
        context_markdown = (
            f"{markdown.rstrip()}\n\n---\n\n"
            f"## Research run metadata\n\n"
            f"- App build: `{build_id}`\n\n"
            f"{job.result or ''}"
        )
        return {
            "markdown": context_markdown,
            "message": (
                "The research report has been added to context. "
                "Please summarize the main findings and include links to the "
                "source artifacts and generated Markdown and HTML reports."
            ),
        }


def build_fast_agent() -> FastAgent:
    """Build the production Harness without model-visible host filesystem access."""
    fast = FastAgent(
        "Hugging Face Researcher",
        parse_cli_args=False,
        home=RESEARCH_HOME,
    )
    fast.load_agents(AGENT_CARDS)
    return fast


def enforce_production_isolation(fast: FastAgent) -> None:
    """Keep model-facing tools off the shared Space host filesystem."""
    fast.app.context.no_shell = True


async def main() -> None:
    args = parse_args()
    fast = build_fast_agent()

    async with fast.harness() as harness:
        enforce_production_isolation(fast)
        build_id = app_build_id(RESEARCH_HOME)
        jobs = ResearchJobStore()
        capabilities = StatusCapabilityStore()
        origin = default_widget_domain()
        if origin is None:
            raise RuntimeError("A public widget domain is required")
        app = FastMCPApp("Hugging Face Researcher")
        register_research_app(
            app,
            jobs=jobs,
            runner=ResearchRunner(harness, RESEARCH_HOME),
            build_id=build_id,
            status_capabilities=capabilities,
            status_origin=origin,
        )

        mcp = FastMCP(
            "researcher",
            auth=auth_provider(),
            instructions="Call `research` to open the live research app.",
        )
        mcp.add_provider(app)
        register_widget_status_route(
            mcp,
            jobs=jobs,
            capabilities=capabilities,
            build_id=build_id,
            origin=origin,
            design=PRODUCTION_UI_DESIGN,
        )
        install_versioned_renderer(
            mcp,
            app_name="Hugging Face Researcher",
            tool_name="researcher",
            build_id=build_id,
            resource_domains=HF_RESOURCE_DOMAINS,
            widget_domain=origin,
        )
        register_landing_page(mcp)
        await mcp.run_http_async(
            transport=args.transport,
            host=args.host,
            port=args.port,
            middleware=http_middleware(),
            stateless_http=use_stateless_http(args.transport),
        )
