from __future__ import annotations

from typing import Any

import httpx
import pytest
from huggingface_hub.errors import BucketNotFoundError

from fast_agent import AgentAuth
from research.research_workspace import (
    _safe_session_segment,
    _session_id,
    ensure_workspace,
    safe_segment,
)


class BucketSimulator:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.create_calls = 0

    def bucket_info(self, bucket_id: str, *, token: str | None) -> None:
        raise self.failure

    def create_bucket(self, *args: Any, **kwargs: Any) -> None:
        self.create_calls += 1

    def batch_bucket_files(self, *args: Any, **kwargs: Any) -> None:
        pass


def auth() -> AgentAuth:
    return AgentAuth.bearer(
        "token",
        provider="huggingface",
        subject="alice",
        claims={"huggingface_whoami": {"name": "alice"}},
    )


def test_only_not_found_creates_bucket() -> None:
    response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://huggingface.co/api/buckets/x"),
    )
    api = BucketSimulator(BucketNotFoundError("missing", response=response))

    workspace = ensure_workspace(
        auth=auth(),
        request_metadata={"request_session_id": "chat"},
        open_metadata={},
        write_markers=False,
        api=api,  # type: ignore[arg-type]
    )

    assert workspace.bucket_created
    assert api.create_calls == 1


def test_clean_session_id_passes_through_unchanged() -> None:
    # The FastMCP-app path supplies a server-generated job id; it must not be
    # rewritten (the report URL depends on it).
    assert _session_id({"request_session_id": "research-0d40b85945be"}, {}) == (
        "research-0d40b85945be"
    )


def test_missing_session_id_is_unique_not_shared_default() -> None:
    first = _session_id({}, {})
    second = _session_id({}, {})
    assert first != second
    assert first.startswith("session-")
    assert first != "default"


def test_truncation_collision_is_disambiguated() -> None:
    a = "y" * 100 + "AAAA"
    b = "y" * 100 + "BBBB"
    # Old behaviour collapsed both to the same 96-char segment.
    assert safe_segment(a) == safe_segment(b)
    assert _safe_session_segment(a) != _safe_session_segment(b)
    assert len(_safe_session_segment(a)) <= 96


def test_char_mapping_collision_is_disambiguated() -> None:
    assert safe_segment("a/b") == safe_segment("a:b")
    assert _safe_session_segment("a/b") != _safe_session_segment("a:b")


def test_session_segment_is_deterministic() -> None:
    assert _safe_session_segment("a/b") == _safe_session_segment("a/b")


def test_transport_failure_does_not_attempt_creation() -> None:
    api = BucketSimulator(httpx.ConnectError("offline"))

    with pytest.raises(httpx.ConnectError):
        ensure_workspace(
            auth=auth(),
            request_metadata={"request_session_id": "chat"},
            open_metadata={},
            write_markers=False,
            api=api,  # type: ignore[arg-type]
        )

    assert api.create_calls == 0
