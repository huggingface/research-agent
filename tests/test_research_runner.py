from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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
