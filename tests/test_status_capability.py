from research.status_capability import StatusCapabilityStore


def test_status_capability_is_opaque_bound_and_expiring() -> None:
    now = 100.0
    store = StatusCapabilityStore(ttl=10, clock=lambda: now)
    token = store.issue("job-1", "owner-1")

    assert "job-1" not in token
    assert store.resolve(token).job_id == "job-1"  # type: ignore[union-attr]
    assert store.resolve(f"{token}x") is None

    now = 111.0
    assert store.resolve(token) is None
