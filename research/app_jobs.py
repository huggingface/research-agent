"""In-memory research job lifecycle with bounded, caller-scoped retention."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from fast_agent import AgentAuth

TERMINAL_STATUSES = {"completed", "failed"}


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


@dataclass(slots=True)
class ResearchJob:
    id: str
    topic: str
    owner_id: str
    status: str = "queued"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    trace_path: str | None = None
    trace_error: str | None = None

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
        return {
            "job_id": self.id,
            "topic": self.topic,
            "status": self.status,
            "events": events,
            "timeline_events": events[-12:],
            "event_count": len(events),
            "elapsed_seconds": int(max(0, elapsed_seconds)),
            "elapsed": format_elapsed(elapsed_seconds),
            "activity_progress": 100 if done else int((elapsed_seconds * 12) % 100),
            "result": self.result,
            "error": self.error,
            "trace_path": self.trace_path,
            "trace_error": self.trace_error,
            "done": done,
        }


@dataclass(frozen=True, slots=True)
class BeginResult:
    job: ResearchJob
    started: bool


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
            job.add_event("Queued research job", now=now)
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
            job.add_event("Starting research agent", now=self._clock())
            return BeginResult(job=job, started=True)

    async def get(self, job_id: str, owner: str) -> ResearchJob | None:
        async with self._lock:
            self._prune(self._clock())
            return self._authorized_job(job_id, owner)

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
        "status": "expired",
        "events": [],
        "timeline_events": [],
        "event_count": 0,
        "elapsed_seconds": 0,
        "elapsed": "00:00",
        "activity_progress": 100,
        "result": None,
        "error": (
            "This research run is no longer available. Historical app views never "
            "start replacement work; ask Claude to run the research tool again."
        ),
        "trace_path": None,
        "trace_error": None,
        "done": True,
    }
