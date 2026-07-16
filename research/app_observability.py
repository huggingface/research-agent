"""Optional timeline and trace-export hooks for research jobs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from fast_agent.mcp.tool_execution_handler import ToolExecutionHandler
from fast_agent.session import SessionTraceExporter
from fast_agent.session.session_manager import SessionManager
from fast_agent.session.trace_export_models import ExportRequest

from .app_jobs import ResearchJob


class JobProgressHandler(ToolExecutionHandler):
    """Project fast-agent tool events into the app's timeline."""

    def __init__(self, job: ResearchJob) -> None:
        self.job = job
        self._labels: dict[str, str] = {}

    async def on_tool_start(
        self,
        tool_name: str,
        server_name: str,
        arguments: dict | None,
        tool_use_id: str | None = None,
    ) -> str:
        tool_call_id = tool_use_id or f"{server_name}/{tool_name}/{uuid4().hex[:8]}"
        label = f"{server_name}/{tool_name}"
        self._labels[tool_call_id] = label
        self.job.add_event(f"{label}: started", kind="tool")
        return tool_call_id

    async def on_tool_progress(
        self,
        tool_call_id: str,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        label = self._labels.get(tool_call_id, "agent")
        self.job.add_event(
            f"{label}: {message or 'working'}",
            kind="progress",
            progress=progress,
            total=total,
        )

    async def on_tool_complete(
        self,
        tool_call_id: str,
        success: bool,
        content: list[Any] | None,
        error: str | None,
    ) -> None:
        label = self._labels.pop(tool_call_id, "agent")
        outcome = "completed" if success else error or "failed"
        self.job.add_event(f"{label}: {outcome}", kind="tool")

    async def on_tool_permission_denied(
        self,
        tool_name: str,
        server_name: str,
        tool_use_id: str | None,
        error: str | None = None,
    ) -> None:
        self.job.add_event(
            f"{server_name}/{tool_name}: {error or 'permission denied'}",
            kind="error",
        )

    async def get_tool_call_id_for_tool_use(
        self,
        tool_use_id: str,
    ) -> str | None:
        return tool_use_id if tool_use_id in self._labels else None

    async def ensure_tool_call_exists(
        self,
        tool_use_id: str,
        tool_name: str,
        server_name: str,
        arguments: dict | None = None,
    ) -> str:
        if tool_use_id in self._labels:
            return tool_use_id
        return await self.on_tool_start(
            tool_name,
            server_name,
            arguments,
            tool_use_id,
        )


def export_trace(job: ResearchJob, home: Path) -> None:
    output_path = (
        home
        / "sessions"
        / "research-traces"
        / job.id
        / f"{job.id}__research__codex.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exporter = SessionTraceExporter(
        session_manager=SessionManager(home_override=home),
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


async def try_export_trace(job: ResearchJob, home: Path) -> None:
    try:
        await asyncio.to_thread(export_trace, job, home)
    except Exception as exc:
        job.trace_error = str(exc)
        job.add_event(f"Trace export failed: {exc}", kind="trace")
