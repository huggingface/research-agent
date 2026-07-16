"""FastMCP App boundary for the research agent."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Any

from fast_agent import FastAgent
from fastmcp import Context as MCPContext
from fastmcp import FastMCP, FastMCPApp
from pydantic import Field
from prefab_ui.app import PrefabApp

from .app_auth import auth_provider, http_middleware, request_auth
from .app_jobs import (
    ResearchJobStore,
    ResearchTaskRegistry,
    owner_id,
    unavailable_snapshot,
)
from .app_ui import build_research_ui
from .research_runner import ResearchRunner

RESEARCH_HOME = Path(__file__).parent
AGENT_CARDS = RESEARCH_HOME / "agent-cards"


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


def register_research_app(
    app: FastMCPApp,
    jobs: ResearchJobStore,
    runner: ResearchRunner,
) -> None:
    """Register one UI entry point and its app-only backend tools."""
    tasks = ResearchTaskRegistry()

    @app.ui(
        name="research",
        title="🤗 Research Agent",
        description="Open a live Hugging Face ecosystem research task.",
    )
    async def research(
        topic: Annotated[str, Field(description="Research topic or task")],
        ctx: MCPContext,
    ) -> PrefabApp:
        auth = request_auth()
        job = await jobs.create(topic, owner_id(auth, ctx.session_id))
        identity = (
            auth.subject or "authenticated user"
            if auth is not None
            else "local development user"
        )
        job.add_event(f"Workspace access confirmed for {identity}.", kind="Setup")
        return build_research_ui(topic, job.snapshot())

    @app.tool()
    async def start_research(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, Any]:
        auth = request_auth()
        result = await jobs.begin(job_id, owner_id(auth, ctx.session_id))
        if result is None:
            return unavailable_snapshot(job_id)
        if result.started:
            tasks.start(result.job.id, runner.run(result.job, auth))
        return result.job.snapshot()

    @app.tool()
    async def research_status(
        job_id: str,
        ctx: MCPContext,
    ) -> dict[str, Any]:
        auth = request_auth()
        job = await jobs.get(job_id, owner_id(auth, ctx.session_id))
        return job.snapshot() if job else unavailable_snapshot(job_id)

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


def build_fast_agent() -> FastAgent:
    """Build the production Harness without model-visible host filesystem access."""
    fast = FastAgent(
        "Research Agent FastMCP App",
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
        app = FastMCPApp("Research Agent")
        register_research_app(
            app,
            jobs=ResearchJobStore(),
            runner=ResearchRunner(harness, RESEARCH_HOME),
        )

        mcp = FastMCP(
            "research-agent-app",
            auth=auth_provider(),
            instructions="Call `research` to open the live research app.",
        )
        mcp.add_provider(app)
        await mcp.run_http_async(
            transport=args.transport,
            host=args.host,
            port=args.port,
            middleware=http_middleware(),
        )
