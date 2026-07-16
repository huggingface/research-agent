from __future__ import annotations

import pytest

from fast_agent import AgentAuth
from research.app_jobs import ResearchJobStore, owner_id, unavailable_snapshot


def bearer(subject: str, token: str = "secret") -> AgentAuth:
    return AgentAuth.bearer(
        token,
        provider="huggingface",
        subject=subject,
    )


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


def test_owner_falls_back_to_token_digest_without_storing_token() -> None:
    auth = AgentAuth.bearer("very-secret", provider="huggingface")
    owner = owner_id(auth, None)
    assert owner.startswith("token:")
    assert "very-secret" not in owner
