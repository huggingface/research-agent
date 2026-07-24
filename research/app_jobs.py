"""In-memory research job lifecycle with bounded, caller-scoped retention."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from fast_agent import AgentAuth

TERMINAL_STATUSES = {"cancelled", "completed", "failed"}
CANCELLABLE_STATUSES = {"queued", "running"}
PHASE_SUMMARIES = {
    "reporting": (
        "The research findings and Markdown report are complete. "
        "The HTML report is now being produced."
    ),
    "wrapping_up": (
        "The Markdown and HTML reports are complete. "
        "The agent is preparing the final response."
    ),
}


def owner_id(auth: AgentAuth | None, session_id: str | None) -> str:
    """Return a non-secret identity suitable for authorizing app backend calls."""
    if auth is not None:
        if auth.subject:
            return f"{auth.provider or 'unknown'}:{auth.subject}"
        if auth.token:
            digest = hashlib.sha256(auth.token.encode()).hexdigest()
            return f"token:{digest}"
    return f"session:{session_id or 'unknown'}"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def display_activity_source(source: str | None) -> str:
    return (source or "researcher/agent_loop").replace("/", " / ")


@dataclass(slots=True)
class ResearchJob:
    id: str
    topic: str
    owner_id: str
    headline: str = "Briefing the researcher"
    workspace_id: str | None = None
    status: str = "queued"
    phase: str = "preparing"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    markdown_report: str | None = None
    markdown_report_uri: str | None = None
    markdown_report_error: str | None = None
    archive_space_url: str | None = None
    archive_app_url: str | None = None
    archive_template_version: str | None = None
    html_report_uri: str | None = None
    html_report_url: str | None = None
    error: str | None = None
    trace_path: str | None = None
    trace_archive_uri: str | None = None
    trace_error: str | None = None
    activity_summary: str = "Briefing the researcher"
    activity_summary_revision: int = 0
    activity_source: str = "researcher/agent_loop"
    activity_summaries: list[dict[str, Any]] = field(default_factory=list)
    event_count_total: int = 0
    turn_count: int = 0
    birch_finalize_attempts: int = 0

    @property
    def artifact_id(self) -> str:
        return self.workspace_id or self.id

    @property
    def harness_session_id(self) -> str:
        """Keep model persistence separate from job and artifact identities."""
        return f"{self.id}-research"

    def add_event(
        self,
        message: str,
        *,
        kind: str = "status",
        progress: float | None = None,
        total: float | None = None,
        now: float | None = None,
    ) -> None:
        self.updated_at = time() if now is None else now
        self.events.append(
            {
                "ts": self.updated_at,
                "kind": kind,
                "message": message,
                "progress": progress,
                "total": total,
            }
        )
        self.event_count_total += 1
        del self.events[:-100]

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time() if now is None else now
        done = self.status in TERMINAL_STATUSES
        elapsed_seconds = (self.updated_at if done else current) - self.created_at
        events = [
            {
                **event,
                "elapsed": format_elapsed(
                    float(event.get("ts") or self.created_at) - self.created_at
                ),
            }
            for event in self.events
        ]
        summaries = [
            {
                **summary,
                "source_label": display_activity_source(summary.get("source")),
                "elapsed": format_elapsed(
                    float(summary.get("ts") or self.created_at) - self.created_at
                ),
            }
            for summary in self.activity_summaries
        ]
        return {
            "job_id": self.id,
            "topic": self.topic,
            "headline": self.headline,
            "workspace_id": self.workspace_id,
            "status": self.status,
            "phase": self.phase,
            "events": events,
            "timeline_events": events[-12:],
            "recent_events": events[-2:],
            "activity_roll": list(
                reversed(
                    [event for event in events if event["kind"] == "Activity"][-6:]
                )
            ),
            "recent_summaries": list(reversed(summaries[:-1][-2:])),
            "event_count": self.event_count_total,
            "elapsed_seconds": int(max(0, elapsed_seconds)),
            "elapsed": format_elapsed(elapsed_seconds),
            "activity_progress": 100 if done else int((elapsed_seconds * 12) % 100),
            "activity_summary": self.activity_summary,
            "activity_summary_revision": self.activity_summary_revision,
            "activity_source": self.activity_source,
            "activity_source_label": display_activity_source(self.activity_source),
            "turn_count": self.turn_count,
            "result": self.result,
            "markdown_report": self.markdown_report,
            "markdown_report_uri": self.markdown_report_uri,
            "markdown_report_error": self.markdown_report_error,
            "archive_space_url": self.archive_space_url,
            "archive_app_url": self.archive_app_url,
            "archive_template_version": self.archive_template_version,
            "html_report_uri": self.html_report_uri,
            "html_report_url": self.html_report_url,
            "html_report_ready": bool(self.html_report_uri),
            "error": self.error,
            "trace_path": self.trace_path,
            "trace_archive_uri": self.trace_archive_uri,
            "trace_error": self.trace_error,
            "done": done,
            "cancellable": self.status in CANCELLABLE_STATUSES,
        }

    def set_activity_summary(self, summary: str, *, now: float | None = None) -> None:
        summary = summary.strip()
        if not summary or summary == self.activity_summary:
            return
        self.activity_summary = summary
        self.activity_summary_revision += 1
        self.updated_at = time() if now is None else now
        self.activity_summaries.append(
            {
                "ts": self.updated_at,
                "message": summary,
                "source": self.activity_source,
            }
        )
        del self.activity_summaries[:-10]

    def record_llm_step(self) -> None:
        self.turn_count += 1
        self.activity_source = "researcher/agent_loop"

    def set_activity_source(self, source: str) -> None:
        if source:
            self.activity_source = source

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        if summary := PHASE_SUMMARIES.get(phase):
            self.set_activity_summary(summary)

    def narrative_for_phase(self, summary: str) -> str:
        return PHASE_SUMMARIES.get(self.phase, summary)


current_research_job: ContextVar[ResearchJob | None] = ContextVar(
    "current_research_job",
    default=None,
)


@dataclass(frozen=True, slots=True)
class BeginResult:
    job: ResearchJob
    started: bool


@dataclass(frozen=True, slots=True)
class CancelResult:
    job: ResearchJob
    cancel_task: bool


class ResearchTaskRegistry:
    """Track cancellable work for one server process."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, job_id: str, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work, name=job_id)
        self._tasks[job_id] = task
        task.add_done_callback(
            lambda completed, job_id=job_id: self._discard(job_id, completed)
        )

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def _discard(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)


class ResearchJobStore:
    def __init__(
        self,
        *,
        completed_ttl: float = 24 * 60 * 60,
        queued_ttl: float = 60 * 60,
        max_jobs: int = 500,
        clock: Callable[[], float] = time,
    ) -> None:
        self._jobs: dict[str, ResearchJob] = {}
        self._lock = asyncio.Lock()
        self._completed_ttl = completed_ttl
        self._queued_ttl = queued_ttl
        self._max_jobs = max_jobs
        self._clock = clock

    async def create(
        self,
        topic: str,
        owner: str,
    ) -> ResearchJob:
        async with self._lock:
            now = self._clock()
            self._prune(now)
            job = ResearchJob(
                id=f"research-{uuid4().hex[:12]}",
                topic=topic,
                owner_id=owner,
                created_at=now,
                updated_at=now,
            )
            job.add_event("Your research request is ready.", kind="Setup", now=now)
            self._jobs[job.id] = job
            self._enforce_limit()
            return job

    async def begin(self, job_id: str, owner: str) -> BeginResult | None:
        """Atomically claim a queued job."""
        async with self._lock:
            self._prune(self._clock())
            job = self._authorized_job(job_id, owner)
            if job is None:
                return None
            if job.status != "queued":
                return BeginResult(job=job, started=False)
            job.status = "running"
            job.phase = "researching"
            job.add_event(
                "The Researcher is getting started.",
                kind="Research",
                now=self._clock(),
            )
            return BeginResult(job=job, started=True)

    async def get(self, job_id: str, owner: str) -> ResearchJob | None:
        async with self._lock:
            self._prune(self._clock())
            return self._authorized_job(job_id, owner)

    async def cancel(self, job_id: str, owner: str) -> CancelResult | None:
        """Atomically request cancellation for an authorized job."""
        async with self._lock:
            self._prune(self._clock())
            job = self._authorized_job(job_id, owner)
            if job is None:
                return None
            if job.status == "queued":
                now = self._clock()
                job.status = "cancelled"
                job.phase = "cancelled"
                job.set_activity_summary(
                    "Research was cancelled before the agent started.",
                    now=now,
                )
                job.add_event("Research cancelled before start", now=now)
                return CancelResult(job=job, cancel_task=False)
            if job.status == "running":
                now = self._clock()
                job.status = "cancelling"
                job.phase = "cancelling"
                job.set_activity_summary(
                    "Cancellation requested. Closing the active research session.",
                    now=now,
                )
                job.add_event("Cancellation requested", now=now)
                return CancelResult(job=job, cancel_task=True)
            return CancelResult(job=job, cancel_task=False)

    def _authorized_job(self, job_id: str, owner: str) -> ResearchJob | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.owner_id == owner else None

    def _prune(self, now: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if (
                job.status in TERMINAL_STATUSES
                and now - job.updated_at >= self._completed_ttl
            )
            or (job.status == "queued" and now - job.updated_at >= self._queued_ttl)
        ]
        for job_id in expired:
            self._jobs.pop(job_id)

    def _enforce_limit(self) -> None:
        excess = len(self._jobs) - self._max_jobs
        if excess <= 0:
            return
        evictable = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status == "queued" or job.status in TERMINAL_STATUSES
            ),
            key=lambda job: job.updated_at,
        )
        for job in evictable[:excess]:
            self._jobs.pop(job.id, None)


def unavailable_snapshot(job_id: str) -> dict[str, Any]:
    """Safe response for expired, restarted, or unauthorized historical apps."""
    return {
        "job_id": job_id,
        "topic": "",
        "headline": "Research unavailable",
        "workspace_id": None,
        "status": "expired",
        "phase": "expired",
        "events": [],
        "timeline_events": [],
        "recent_events": [],
        "activity_roll": [],
        "recent_summaries": [],
        "event_count": 0,
        "elapsed_seconds": 0,
        "elapsed": "00:00",
        "activity_progress": 100,
        "activity_summary": "This research run is no longer available.",
        "activity_summary_revision": 0,
        "activity_source": "researcher/agent_loop",
        "activity_source_label": "research / agent_loop",
        "turn_count": 0,
        "result": None,
        "markdown_report": None,
        "markdown_report_uri": None,
        "markdown_report_error": None,
        "archive_space_url": None,
        "archive_app_url": None,
        "archive_template_version": None,
        "html_report_uri": None,
        "html_report_url": None,
        "html_report_ready": False,
        "error": (
            "This research run is no longer available. Historical app views never "
            "start replacement work; ask Claude to run the research tool again."
        ),
        "trace_path": None,
        "trace_archive_uri": None,
        "trace_error": None,
        "done": True,
        "cancellable": False,
    }
