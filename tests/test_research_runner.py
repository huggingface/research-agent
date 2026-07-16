from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import pytest

from fast_agent import AgentAuth
from research.app_jobs import ResearchJob
from research.research_runner import ResearchRunner


class ResponseSimulator:
    def text_content(self) -> str:
        return "finished"


class SessionSimulator:
    def __init__(self) -> None:
        self.request: Any = None

    async def invoke(self, request: Any) -> ResponseSimulator:
        self.request = request
        return ResponseSimulator()


class AppSimulator:
    def __init__(self, session: SessionSimulator) -> None:
        self.session = session
        self.open_request: Any = None

    @asynccontextmanager
    async def open(self, request: Any):
        self.open_request = request
        yield self.session


class HarnessSimulator:
    def __init__(self) -> None:
        self.session = SessionSimulator()
        self.application = AppSimulator(self.session)
        self.auth: AgentAuth | None = None

    @contextmanager
    def request_context(self, *, auth: AgentAuth | None):
        self.auth = auth
        yield

    def app(self) -> AppSimulator:
        return self.application


@pytest.mark.asyncio
async def test_runner_uses_one_explicit_harness_session() -> None:
    harness = HarnessSimulator()
    runner = ResearchRunner(harness, Path("."))  # type: ignore[arg-type]
    auth = AgentAuth.bearer(
        "token",
        provider="huggingface",
        subject="alice",
    )
    job = ResearchJob(id="job-1", topic="Research MCP Apps", owner_id="alice")

    result = await runner.invoke(job, auth)

    assert result == "finished"
    assert harness.auth is auth
    assert harness.application.open_request.session_id == job.id
    assert harness.session.request.session_id == job.id
    assert harness.session.request.agent == "research"
    assert harness.session.request.auth is auth
