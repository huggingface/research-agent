"""Experimental FastMCP App wrapper for the research agent.

Run from this repository with the adjacent fast-agent checkout, for example:

    uv run --project ../fast-agent python fastmcp_research_app.py

Then connect an MCP/FastMCP Apps-capable client to the HTTP endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Annotated, Any, cast
from uuid import uuid4

from fast_agent import AgentAuth, AgentRequest, AppOpenRequest, FastAgent
from fast_agent.llm.request_params import RequestParams
from fast_agent.mcp.server import HarnessMCPAdapter
from fast_agent.mcp.tool_execution_handler import ToolExecutionHandler
from fast_agent.session import SessionTraceExporter
from fast_agent.session.session_manager import SessionManager
from fast_agent.session.trace_export_models import ExportRequest
from fastmcp import Context as MCPContext
from fastmcp import FastMCP, FastMCPApp
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl, Field
from starlette.middleware import Middleware

from prefab_ui.actions import SetInterval, SetState
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import Badge, Card, CardContent, CardHeader, Column, Heading, If, Loader, Markdown, Muted, Progress, Row, Text
from prefab_ui.components.control_flow import Else, ForEach
from prefab_ui.rx import RESULT, Rx, STATE

from fast_agent.mcp.auth.middleware import HFAuthHeaderMiddleware
from fast_agent.mcp.server.common import get_oauth_config, normalize_serve_oauth_provider

HERE = Path(__file__).parent
RESEARCH_HOME = HERE / "research"
AGENT_CARDS = RESEARCH_HOME / "agent-cards"

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the research agent as a FastMCP App experiment.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8724)
    parser.add_argument(
        "--transport",
        choices=("http", "streamable-http", "sse"),
        default="http",
        help="FastMCP HTTP-family transport to expose.",
    )
    return parser.parse_args()


def auth_provider() -> RemoteAuthProvider | None:
    oauth_provider, oauth_scopes, resource_url = get_oauth_config()
    if oauth_provider != "huggingface":
        return None

    from fast_agent.mcp.auth.providers.huggingface import HuggingFaceTokenVerifier

    return RemoteAuthProvider(
        token_verifier=HuggingFaceTokenVerifier(),
        authorization_servers=[AnyHttpUrl("https://huggingface.co")],
        base_url=AnyHttpUrl(resource_url),
        scopes_supported=oauth_scopes,
        resource_name="research-agent-app",
    )


def http_middleware() -> list[Middleware] | None:
    oauth_provider = normalize_serve_oauth_provider(os.environ.get("FAST_AGENT_SERVE_OAUTH"))
    if oauth_provider != "huggingface":
        return None
    return [Middleware(cast(Any, HFAuthHeaderMiddleware))]


@dataclass(slots=True)
class ResearchJob:
    id: str
    topic: str
    auth: AgentAuth | None
    status: str = "queued"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    trace_path: str | None = None
    trace_error: str | None = None

    def add_event(self, message: str, *, kind: str = "status", progress: float | None = None, total: float | None = None) -> None:
        self.updated_at = time()
        self.events.append(
            {
                "ts": self.updated_at,
                "kind": kind,
                "message": message,
                "progress": progress,
                "total": total,
            }
        )
        del self.events[:-100]

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "topic": self.topic,
            "status": self.status,
            "events": list(self.events),
            "timeline_events": list(self.events[-12:]),
            "event_count": len(self.events),
            "activity_progress": 100 if self.status in {"completed", "failed"} else int(((time() - self.created_at) * 12) % 100),
            "result": self.result,
            "error": self.error,
            "trace_path": self.trace_path,
            "trace_error": self.trace_error,
            "done": self.status in {"completed", "failed"},
        }


class ResearchJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ResearchJob] = {}
        self._lock = asyncio.Lock()

    async def create(self, topic: str, auth: AgentAuth | None) -> ResearchJob:
        async with self._lock:
            job = ResearchJob(id=f"research-{uuid4().hex[:12]}", topic=topic, auth=auth)
            job.add_event("Queued research job")
            self._jobs[job.id] = job
            return job

    async def get(self, job_id: str) -> ResearchJob | None:
        async with self._lock:
            return self._jobs.get(job_id)


def export_job_trace(job: ResearchJob) -> None:
    """Export the persisted fast-agent session for a completed job to Codex JSONL."""
    output_path = RESEARCH_HOME / "sessions" / "research-traces" / job.id / f"{job.id}__research__codex.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manager = SessionManager(home_override=RESEARCH_HOME)
    exporter = SessionTraceExporter(
        session_manager=manager,
        progress_callback=lambda message: job.add_event(message, kind="trace"),
    )
    result = exporter.export(
        ExportRequest(
            target=job.id,
            agent_name="research",
            output_path=output_path,
        )
    )
    job.trace_path = str(result.output_path)
    job.add_event(
        f"Exported Codex trace: {result.output_path} ({result.record_count} records)",
        kind="trace",
    )


async def try_export_job_trace(job: ResearchJob) -> None:
    try:
        await asyncio.to_thread(export_job_trace, job)
    except Exception as exc:
        job.trace_error = str(exc)
        job.add_event(f"Trace export failed: {exc}", kind="trace")


class JobProgressHandler(ToolExecutionHandler):
    def __init__(self, job: ResearchJob) -> None:
        self.job = job
        self._labels: dict[str, str] = {}

    async def on_tool_start(self, tool_name: str, server_name: str, arguments: dict | None, tool_use_id: str | None = None) -> str:
        tool_call_id = tool_use_id or f"{server_name}/{tool_name}/{uuid4().hex[:8]}"
        label = f"{server_name}/{tool_name}"
        self._labels[tool_call_id] = label
        self.job.add_event(f"{label}: started", kind="tool")
        return tool_call_id

    async def on_tool_progress(self, tool_call_id: str, progress: float, total: float | None, message: str | None) -> None:
        label = self._labels.get(tool_call_id, "agent")
        self.job.add_event(f"{label}: {message or 'working'}", kind="progress", progress=progress, total=total)

    async def on_tool_complete(self, tool_call_id: str, success: bool, content: list[Any] | None, error: str | None) -> None:
        label = self._labels.pop(tool_call_id, "agent")
        self.job.add_event(f"{label}: {'completed' if success else error or 'failed'}", kind="tool")

    async def on_tool_permission_denied(self, tool_name: str, server_name: str, tool_use_id: str | None, error: str | None = None) -> None:
        self.job.add_event(f"{server_name}/{tool_name}: {error or 'permission denied'}", kind="error")

    async def get_tool_call_id_for_tool_use(self, tool_use_id: str) -> str | None:
        return tool_use_id if tool_use_id in self._labels else None

    async def ensure_tool_call_exists(self, tool_use_id: str, tool_name: str, server_name: str, arguments: dict | None = None) -> str:
        if tool_use_id in self._labels:
            return tool_use_id
        return await self.on_tool_start(tool_name, server_name, arguments, tool_use_id)


async def main() -> None:
    args = parse_args()

    fast = FastAgent(
        "Research Agent FastMCP App Experiment",
        parse_cli_args=False,
        home=RESEARCH_HOME,
    )
    fast.load_agents(AGENT_CARDS)

    async with fast.harness() as harness:
        app = FastMCPApp("Research Agent")
        mcp = FastMCP(
            "research-agent-app",
            auth=auth_provider(),
            instructions=(
                "Call `research` to open a live research app. The app starts the "
                "fast-agent research workflow and shows ongoing LLM/tool progress."
            ),
        )
        jobs = ResearchJobStore()

        async def run_job(job: ResearchJob) -> None:
            job.status = "running"
            job.add_event("Starting research agent")
            try:
                with harness.request_context(auth=job.auth):
                    async with harness.app().open(
                        AppOpenRequest(
                            session_id=job.id,
                            agent="research",
                            metadata={"fastmcp_app_job_id": job.id},
                        )
                    ) as session:
                        response = await session.invoke(
                            AgentRequest.text(
                                job.topic,
                                agent="research",
                                session_id=job.id,
                                auth=job.auth,
                                params=RequestParams(
                                    tool_execution_handler=JobProgressHandler(job),
                                    emit_loop_progress=True,
                                ),
                                metadata={"fastmcp_app_job_id": job.id},
                            )
                        )
                job.result = response.text_content()
                await try_export_job_trace(job)
                job.status = "completed"
                job.add_event("Research completed")
            except Exception as exc:
                job.error = str(exc)
                await try_export_job_trace(job)
                job.status = "failed"
                job.add_event(f"Research failed: {exc}", kind="error")

        @app.ui(
            name="research",
            title="🤗 Research Agent",
            description="Open a live research app for a Hugging Face ecosystem research task.",
        )
        async def research(
            topic: Annotated[str, Field(description="Research topic or task")],
            ctx: MCPContext,
        ) -> PrefabApp:
            del ctx
            auth = HarnessMCPAdapter.agent_auth()
            job = await jobs.create(topic, auth)
            if auth is None:
                job.add_event("No AgentAuth was captured from the MCP app entrypoint", kind="auth")
            else:
                scopes = ", ".join(auth.scopes) if auth.scopes else "<none/unknown>"
                subject = auth.subject or "<unknown>"
                provider = auth.provider or "<unknown>"
                job.add_event(
                    f"Captured auth provider={provider} subject={subject} scopes={scopes} token_present={bool(auth.token)}",
                    kind="auth",
                )

            with PrefabApp(
                state={
                    "job": job.snapshot(),
                    "topic": topic,
                    "job_id": job.id,
                    "poll_ms": "1500",
                    "started": False,
                }
            ) as ui:
                with Column(
                    gap=4,
                    css_class="p-6",
                    on_mount=[
                        CallTool(
                            "start_research",
                            arguments={"job_id": STATE.job_id},
                            on_success=[
                                SetState("started", True),
                                SetState("job", RESULT),
                                SetState("poll_ms", RESULT.done.then("86400000", "1500")),
                            ],
                        ),
                        SetInterval(
                            duration=STATE.poll_ms,
                            on_tick=CallTool(
                                "research_status",
                                arguments={"job_id": STATE.job_id},
                                on_success=[
                                    SetState("job", RESULT),
                                    SetState("poll_ms", RESULT.done.then("86400000", "1500")),
                                ],
                            ),
                        ),
                    ],
                ):
                    with Row(justify="between", align="center"):
                        Heading("🤗 Research Agent")
                        Badge(STATE.job.status, variant="outline")
                    Muted(STATE.topic)

                    with Card():
                        with CardHeader():
                            Text("Activity")
                        with CardContent():
                            with If("{{ !job.done }}"):
                                with Row(gap=3, align="center"):
                                    Loader(variant="bars", size="sm")
                                    Badge(STATE.job.status, variant="outline")
                                    Muted("Working; the number of steps is not known in advance.")
                            with Else():
                                with Row(gap=3, align="center"):
                                    Badge(STATE.job.status, variant="outline")
                                    Muted("No active work.")
                            Progress(value=STATE.job.activity_progress, max=100, gradient=True, size="sm")

                    with Card():
                        with CardHeader():
                            Text("Timeline")
                            Muted("Showing the latest 12 events; older events roll off the visible list.")
                        with CardContent():
                            with ForEach("job.timeline_events") as event:
                                with Row(gap=2, align="start"):
                                    Badge(event.kind, variant="outline")
                                    Text(event.message)

                    with If(STATE.job.error):
                        with Card():
                            with CardHeader():
                                Text("Error")
                            with CardContent():
                                Text(STATE.job.error, css_class="text-red-600")

                    with If(STATE.job.trace_path):
                        with Card():
                            with CardHeader():
                                Text("Session trace")
                            with CardContent():
                                Text(STATE.job.trace_path, css_class="font-mono text-sm")

                    with If(STATE.job.trace_error):
                        with Card():
                            with CardHeader():
                                Text("Trace export")
                            with CardContent():
                                Text(STATE.job.trace_error, css_class="text-amber-600")

                    with If(STATE.job.result):
                        with Card():
                            with CardHeader():
                                Text("Final result")
                            with CardContent():
                                Markdown(STATE.job.result, css_class="whitespace-pre-wrap")

            return ui

        @app.tool()
        async def start_research(job_id: str) -> dict[str, Any]:
            job = await jobs.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "failed", "error": "Unknown research job", "events": [], "done": True}
            if job.status == "queued":
                task = asyncio.create_task(run_job(job))
                _BACKGROUND_TASKS.add(task)
                task.add_done_callback(_BACKGROUND_TASKS.discard)
            return job.snapshot()

        @app.tool()
        async def research_status(job_id: str) -> dict[str, Any]:
            job = await jobs.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "failed", "error": "Unknown research job", "events": [], "done": True}
            return job.snapshot()

        mcp.add_provider(app)
        await mcp.run_http_async(
            transport=args.transport,
            host=args.host,
            port=args.port,
            middleware=http_middleware(),
        )


if __name__ == "__main__":
    asyncio.run(main())
