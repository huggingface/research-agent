from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fast_agent import AgentAuth
from research.app_jobs import ResearchJob
from research.research_runner import ResearchRunner


class BlockingResearchRunner(ResearchRunner):
    def __init__(self, home: Path) -> None:
        super().__init__(harness=None, home=home)  # type: ignore[arg-type]
        self.started = asyncio.Event()

    async def invoke(self, job: ResearchJob, auth: None) -> str:
        self.started.set()
        await asyncio.Event().wait()
        return "unreachable"


class SuccessfulResearchRunner(ResearchRunner):
    def __init__(self, home: Path) -> None:
        super().__init__(harness=None, home=home)  # type: ignore[arg-type]

    async def invoke(self, job: ResearchJob, auth: None) -> str:
        job.markdown_report = "# Findings"
        return "Complete"

    async def build_html_report(self, job: ResearchJob, auth: None) -> None:
        job.html_report_uri = "hf://bucket/report.html"
        job.html_report_url = "https://example.com/report.html"


class RetryingReportRunner(ResearchRunner):
    def __init__(self, home: Path, *, failures: int) -> None:
        super().__init__(harness=None, home=home)  # type: ignore[arg-type]
        self.failures = failures
        self.invocations = 0
        self.finalizations = 0

    async def _invoke_html_agent(
        self,
        job: ResearchJob,
        auth: AgentAuth,
        attempt: int,
    ) -> None:
        self.invocations += 1

    async def _finalize_html(
        self,
        job: ResearchJob,
        auth: AgentAuth,
    ) -> tuple[str, str]:
        self.finalizations += 1
        if self.finalizations <= self.failures:
            raise ValueError("draft validation failed")
        return "hf://bucket/report.html", "https://example.com/report.html"


class FailingResearchRunner(ResearchRunner):
    async def invoke(self, job: ResearchJob, auth: None) -> str:
        raise RuntimeError("source endpoint returned HTTP 429")


@pytest.mark.asyncio
async def test_runner_records_cancelled_terminal_state(tmp_path: Path) -> None:
    runner = BlockingResearchRunner(tmp_path)
    job = ResearchJob(id="research-test", topic="topic", owner_id="alice")
    job.status = "running"
    task = asyncio.create_task(runner.run(job, None))
    await runner.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    snapshot = job.snapshot()
    assert snapshot["status"] == "cancelled"
    assert snapshot["done"]
    assert not snapshot["cancellable"]
    assert snapshot["result"] is None
    assert "cancelled" in snapshot["activity_summary"].lower()


@pytest.mark.asyncio
async def test_runner_records_completed_terminal_narrative(
    tmp_path: Path,
) -> None:
    job = ResearchJob(id="research-test", topic="topic", owner_id="alice")

    await SuccessfulResearchRunner(tmp_path).run(job, None)

    assert job.status == "completed"
    assert "ready to review" in job.activity_summary
    assert "interactive HTML report" in job.activity_summary
    assert job.html_report_uri == "hf://bucket/report.html"


@pytest.mark.asyncio
async def test_runner_records_failure_as_terminal_narrative(tmp_path: Path) -> None:
    runner = FailingResearchRunner(
        harness=None,  # type: ignore[arg-type]
        home=tmp_path,
    )
    job = ResearchJob(id="research-test", topic="topic", owner_id="alice")

    await runner.run(job, None)

    assert job.status == "failed"
    assert "HTTP 429" in job.activity_summary
    assert "final report" in job.activity_summary


@pytest.mark.asyncio
async def test_html_report_stage_retries_then_publishes(tmp_path: Path) -> None:
    runner = RetryingReportRunner(tmp_path, failures=1)
    job = ResearchJob(id="research-test", topic="topic", owner_id="alice")

    await runner.build_html_report(job, AgentAuth.bearer("token"))

    assert runner.invocations == 2
    assert runner.finalizations == 2
    assert job.birch_finalize_attempts == 2
    assert job.html_report_uri == "hf://bucket/report.html"
    assert any("attempt 1 failed" in event["message"] for event in job.events)


@pytest.mark.asyncio
async def test_html_report_stage_fails_after_two_attempts(tmp_path: Path) -> None:
    runner = RetryingReportRunner(tmp_path, failures=2)
    job = ResearchJob(id="research-test", topic="topic", owner_id="alice")

    with pytest.raises(
        RuntimeError,
        match="HTML report generation failed after 2 attempts",
    ):
        await runner.build_html_report(job, AgentAuth.bearer("token"))

    assert runner.invocations == 2
    assert runner.finalizations == 2
    assert job.birch_finalize_attempts == 2
