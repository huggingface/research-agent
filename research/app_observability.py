"""Optional timeline and trace-export hooks for research jobs."""

from __future__ import annotations

import asyncio
import os
import posixpath
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from huggingface_hub import HfApi, HfFileSystem
from huggingface_hub.errors import BucketNotFoundError

from fast_agent.mcp.tool_execution_handler import ToolExecutionHandler
from fast_agent.session import SessionTraceExporter
from fast_agent.session.session_manager import SessionManager
from fast_agent.session.trace_export_models import ExportRequest

from .app_jobs import ResearchJob
from .research_workspace import ResearchWorkspace, current_research_workspace

MarkdownReader = Callable[[ResearchWorkspace], Awaitable[str]]
MAX_MARKDOWN_REPORT_CHARS = 250_000
ARCHIVE_URL_ENV = "RESEARCH_ARCHIVE_HF_URL"
ARCHIVE_TOKEN_ENV = "RESEARCH_ARCHIVE_TOKEN"


@dataclass(frozen=True, slots=True)
class ArchiveTarget:
    bucket_id: str
    root: str


class JobProgressHandler(ToolExecutionHandler):
    """Project fast-agent tool events into the app's timeline."""

    def __init__(self, job: ResearchJob) -> None:
        self.job = job
        self._activities: dict[str, tuple[str, str, str, str]] = {}

    async def on_tool_start(
        self,
        tool_name: str,
        server_name: str,
        arguments: dict | None,
        tool_use_id: str | None = None,
    ) -> str:
        tool_call_id = tool_use_id or f"{server_name}/{tool_name}/{uuid4().hex[:8]}"
        activity = _tool_activity(server_name, tool_name, arguments)
        self._activities[tool_call_id] = activity
        self.job.set_activity_source(activity[0])
        self.job.add_event(f"{activity[0]}: started", kind="Activity")
        if _is_birch_delegation(server_name, tool_name):
            self.job.set_phase("reporting")
            await capture_markdown_report(self.job)
        return tool_call_id

    async def on_tool_progress(
        self,
        tool_call_id: str,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        del progress, total
        source = self._activities.get(
            tool_call_id,
            ("researcher/agent_loop", "Researcher", "Research", ""),
        )[0]
        self.job.set_activity_source(source)
        self.job.add_event(f"{source}: {message or 'working'}", kind="Activity")

    async def on_tool_complete(
        self,
        tool_call_id: str,
        success: bool,
        content: list[Any] | None,
        error: str | None,
    ) -> None:
        raw_source, source, category, completed = self._activities.pop(
            tool_call_id,
            (
                "researcher/agent_loop",
                "Researcher",
                "Research",
                "A research step finished.",
            ),
        )
        message = completed if success else _friendly_tool_error(source, error)
        self.job.add_event(
            f"{raw_source}: completed" if success else message,
            kind="Activity",
        )
        self.job.set_activity_source(
            next(
                (activity[0] for activity in reversed(self._activities.values())),
                "researcher/agent_loop",
            )
        )
        if _is_birch_delegation(*raw_source.split("/", 1)):
            self.job.set_phase("wrapping_up" if success else "researching")

    async def on_tool_permission_denied(
        self,
        tool_name: str,
        server_name: str,
        tool_use_id: str | None,
        error: str | None = None,
    ) -> None:
        raw_source, source, _, _ = _tool_activity(server_name, tool_name, None)
        self.job.set_activity_source(raw_source)
        self.job.add_event(
            _friendly_tool_error(source, error or "Permission was denied."),
            kind="Activity",
        )

    async def get_tool_call_id_for_tool_use(
        self,
        tool_use_id: str,
    ) -> str | None:
        return tool_use_id if tool_use_id in self._activities else None

    async def ensure_tool_call_exists(
        self,
        tool_use_id: str,
        tool_name: str,
        server_name: str,
        arguments: dict | None = None,
    ) -> str:
        if tool_use_id in self._activities:
            return tool_use_id
        return await self.on_tool_start(
            tool_name,
            server_name,
            arguments,
            tool_use_id,
        )


def _tool_activity(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> tuple[str, str, str, str]:
    raw_source = f"{server_name}/{tool_name}"
    raw_name = f"{server_name}/{tool_name}".lower()
    if "birch-html" in raw_name:
        return (
            raw_source,
            "Report writer",
            "Report",
            "The report writer finished another section.",
        )
    if tool_name == "agent_loop":
        return (
            raw_source,
            "Researcher",
            "Research",
            "The agent completed a research step.",
        )
    if server_name == "hf" and tool_name == "hf_fs":
        command = str((arguments or {}).get("cmd") or "").lower()
        if command == "search":
            return (
                raw_source,
                "Searching Hugging Face",
                "Hugging Face",
                "The Hugging Face search finished.",
            )
        if command == "cat":
            return (
                raw_source,
                "Reading a Hugging Face source",
                "Hugging Face",
                "The agent finished reading a Hugging Face source.",
            )
        return (
            raw_source,
            "Browsing Hugging Face",
            "Hugging Face",
            "The Hugging Face lookup finished.",
        )
    if server_name == "hf" and "sandbox" in tool_name:
        return (
            raw_source,
            "Running analysis",
            "Analysis",
            "The latest analysis step finished.",
        )
    readable = tool_name.split("[", 1)[0].replace("_", " ").replace("-", " ")
    return (
        raw_source,
        readable.capitalize(),
        "Research",
        f"The agent finished {readable}.",
    )


def _is_birch_delegation(server_name: str, tool_name: str) -> bool:
    return server_name == "agent" and tool_name.split("[", 1)[0] == "birch-html"


async def capture_markdown_report(
    job: ResearchJob,
    *,
    reader: MarkdownReader | None = None,
) -> None:
    workspace = current_research_workspace.get()
    if workspace is None:
        return
    uri = f"{workspace.output}report.md"
    try:
        markdown = await (reader or _read_markdown_report)(workspace)
    except Exception as exc:
        job.markdown_report_error = str(exc)
        return

    if len(markdown) > MAX_MARKDOWN_REPORT_CHARS:
        markdown = (
            markdown[:MAX_MARKDOWN_REPORT_CHARS].rstrip()
            + "\n\n_This in-app preview was truncated; open the artifact for the full report._"
        )
    job.markdown_report = markdown
    job.markdown_report_uri = uri
    job.markdown_report_error = None
    job.archive_space_url = workspace.archive_space_url
    job.archive_app_url = workspace.archive_app_url
    job.archive_template_version = workspace.archive_installed_version
    job.add_event("The Markdown report is ready to review.", kind="Report")


async def _read_markdown_report(workspace: ResearchWorkspace) -> str:
    def read() -> str:
        filesystem = HfFileSystem(token=workspace.bearer_token)
        with filesystem.open(f"{workspace.output}report.md", "r") as report:
            return str(report.read())

    return await asyncio.to_thread(read)


def _friendly_tool_error(source: str, error: str | None) -> str:
    detail = (error or "The operation did not complete.").strip()
    if "search requires a positional query or --query" in detail:
        return "A Hugging Face search request was missing its query."
    detail = detail.removeprefix("EINVAL:").strip()
    if len(detail) > 180:
        detail = f"{detail[:177].rstrip()}…"
    return f"{source} encountered a problem: {detail}"


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
            target=job.harness_session_id,
            agent_name="researcher",
            output_path=output_path,
        )
    )
    job.trace_path = str(result.output_path)
    job.add_event(
        f"Exported Codex trace: {result.output_path} ({result.record_count} records)",
        kind="trace",
    )
    archive = _archive_config()
    if archive is not None:
        target, token = archive
        job.trace_archive_uri = archive_session(
            job,
            home,
            result.output_path,
            target=target,
            token=token,
        )
        job.add_event(
            f"Archived private session: {job.trace_archive_uri}",
            kind="trace",
        )


def _archive_config() -> tuple[ArchiveTarget, str] | None:
    url = os.getenv(ARCHIVE_URL_ENV, "").strip()
    token = os.getenv(ARCHIVE_TOKEN_ENV, "").strip()
    if not url and not token:
        return None
    if not url or not token:
        missing = ARCHIVE_URL_ENV if not url else ARCHIVE_TOKEN_ENV
        raise RuntimeError(f"Private session archive is missing {missing}.")
    return _archive_target(url), token


def _archive_target(url: str) -> ArchiveTarget:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "hf" or parsed.netloc != "buckets" or len(parts) < 2:
        raise ValueError(
            f"{ARCHIVE_URL_ENV} must be an hf://buckets/<owner>/<bucket> URL."
        )
    bucket_id = f"{parts[0]}/{parts[1]}"
    prefix = "/".join(parts[2:])
    root = f"hf://buckets/{bucket_id}"
    if prefix:
        root = f"{root}/{prefix}"
    return ArchiveTarget(bucket_id=bucket_id, root=root)


def archive_session(
    job: ResearchJob,
    home: Path,
    trace_path: Path,
    *,
    target: ArchiveTarget,
    token: str,
    api: Any | None = None,
    filesystem: Any | None = None,
) -> str:
    """Archive one raw session and Codex trace using an app-only credential."""
    api = api or HfApi(token=token)
    filesystem = filesystem or HfFileSystem(token=token)
    try:
        info = api.bucket_info(target.bucket_id, token=token)
    except BucketNotFoundError:
        api.create_bucket(
            target.bucket_id,
            private=True,
            exist_ok=True,
            token=token,
        )
    else:
        if not bool(getattr(info, "private", False)):
            raise RuntimeError(
                f"Refusing to archive sessions to public bucket {target.bucket_id!r}."
            )

    session_dir = home / "sessions" / job.harness_session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Session directory does not exist: {session_dir}")
    for source in sorted(path for path in session_dir.rglob("*") if path.is_file()):
        relative = source.relative_to(session_dir).as_posix()
        _upload_archive_file(
            filesystem,
            source,
            f"{target.root}/{job.id}/{relative}",
        )

    trace_uri = (
        f"{target.root}/research-traces/{job.id}/{posixpath.basename(trace_path)}"
    )
    _upload_archive_file(filesystem, trace_path, trace_uri)
    return trace_uri


def _upload_archive_file(filesystem: Any, source: Path, destination: str) -> None:
    with (
        source.open("rb") as source_file,
        filesystem.open(destination, "wb") as destination_file,
    ):
        destination_file.write(source_file.read())


async def try_export_trace(job: ResearchJob, home: Path) -> None:
    try:
        await asyncio.to_thread(export_trace, job, home)
    except Exception as exc:
        job.trace_error = str(exc)
        job.add_event(f"Trace export failed: {exc}", kind="trace")
