from __future__ import annotations

import asyncio

import pytest

from fast_agent import AgentAuth
from research.app_jobs import (
    ResearchJob,
    ResearchJobStore,
    ResearchTaskRegistry,
    owner_id,
    unavailable_snapshot,
)


def bearer(subject: str, token: str = "secret") -> AgentAuth:
    return AgentAuth.bearer(
        token,
        provider="huggingface",
        subject=subject,
    )


def test_status_snapshot_excludes_report_payload() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")
    job.markdown_report = "# Report\n\nPrivate report body."
    job.markdown_report_blocks = [
        {"kind": "image", "src": "data:image/png;base64,c2VjcmV0", "alt": "Chart"}
    ]
    job.markdown_report_uri = "hf://buckets/alice/research/output/report.md"

    snapshot = job.snapshot()

    assert snapshot["markdown_report_ready"]
    assert "markdown_report" not in snapshot
    assert "markdown_report_blocks" not in snapshot
    assert "Private report body" not in str(snapshot)
    assert "data:image" not in str(snapshot)


@pytest.mark.asyncio
async def test_begin_is_idempotent_without_storing_token() -> None:
    auth = bearer("alice")
    owner = owner_id(auth, None)
    store = ResearchJobStore()
    job = await store.create("topic", owner)

    first = await store.begin(job.id, owner)
    second = await store.begin(job.id, owner)

    assert first is not None and first.started
    assert second is not None and not second.started
    assert not hasattr(job, "_auth")
    assert job.status == "running"


@pytest.mark.asyncio
async def test_jobs_are_caller_bound_without_disclosing_existence() -> None:
    alice = bearer("alice")
    store = ResearchJobStore()
    job = await store.create("private topic", owner_id(alice, None))

    assert await store.get(job.id, owner_id(bearer("bob"), None)) is None
    snapshot = unavailable_snapshot(job.id)
    assert snapshot["status"] == "expired"
    assert "private topic" not in str(snapshot)


@pytest.mark.asyncio
async def test_completed_jobs_expire_without_restarting() -> None:
    now = 100.0
    store = ResearchJobStore(completed_ttl=10, clock=lambda: now)
    auth = bearer("alice")
    owner = owner_id(auth, None)
    job = await store.create("topic", owner)
    result = await store.begin(job.id, owner)
    assert result is not None
    job.status = "completed"
    job.add_event("done", now=now)

    now = 111.0
    assert await store.get(job.id, owner) is None
    assert await store.begin(job.id, owner) is None


@pytest.mark.asyncio
async def test_running_job_cancellation_is_idempotent() -> None:
    store = ResearchJobStore()
    job = await store.create("topic", "alice")
    await store.begin(job.id, "alice")

    first = await store.cancel(job.id, "alice")
    second = await store.cancel(job.id, "alice")

    assert first is not None and first.cancel_task
    assert second is not None and not second.cancel_task
    assert job.status == "cancelling"
    assert not job.snapshot()["cancellable"]


@pytest.mark.asyncio
async def test_queued_job_can_be_cancelled_without_a_task() -> None:
    store = ResearchJobStore()
    job = await store.create("topic", "alice")

    result = await store.cancel(job.id, "alice")

    assert result is not None and not result.cancel_task
    assert job.status == "cancelled"
    assert job.snapshot()["done"]
    assert not (await store.begin(job.id, "alice")).started


@pytest.mark.asyncio
async def test_task_registry_cancels_and_discards_work() -> None:
    registry = ResearchTaskRegistry()
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def work() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    registry.start("job", work())
    await started.wait()

    assert registry.cancel("job")
    await stopped.wait()
    await asyncio.sleep(0)
    assert not registry.cancel("job")


def test_owner_falls_back_to_token_digest_without_storing_token() -> None:
    auth = AgentAuth.bearer("very-secret", provider="huggingface")
    owner = owner_id(auth, None)
    assert owner.startswith("token:")
    assert "very-secret" not in owner


@pytest.mark.asyncio
async def test_activity_summary_is_exposed_without_cluttering_timeline() -> None:
    store = ResearchJobStore()
    job = await store.create("topic", "alice")
    original_events = len(job.events)

    job.set_activity_summary("Reviewing official model configurations.")
    snapshot = job.snapshot()

    assert snapshot["activity_summary"] == "Reviewing official model configurations."
    assert snapshot["activity_summary_revision"] == 1
    assert len(job.events) == original_events


def test_snapshot_keeps_only_two_previous_narratives() -> None:
    job = ResearchJob(
        id="job",
        topic="topic",
        owner_id="alice",
        created_at=100,
        updated_at=100,
    )
    for index in range(4):
        job.set_activity_summary(f"Summary {index}", now=110 + index)

    snapshot = job.snapshot(now=120)

    assert [item["message"] for item in snapshot["recent_summaries"]] == [
        "Summary 2",
        "Summary 1",
    ]
    assert snapshot["activity_source_label"] == "researcher / agent_loop"
    assert all(
        item["source_label"] == "researcher / agent_loop"
        for item in snapshot["recent_summaries"]
    )


def test_event_count_is_not_limited_by_retained_history() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")
    for index in range(105):
        job.add_event(f"Event {index}")

    snapshot = job.snapshot()

    assert snapshot["event_count"] == 105
    assert len(snapshot["events"]) == 100

    for index in range(20):
        job.add_event(f"Birch activity {index}", kind="Activity")

    snapshot = job.snapshot()
    assert snapshot["event_count"] == 125
    assert len(snapshot["events"]) == 100
    assert len(snapshot["activity_roll"]) == 6
