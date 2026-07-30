from __future__ import annotations

from typing import Any

import httpx
import pytest
from fast_agent import AgentAuth
from huggingface_hub.errors import BucketNotFoundError

from research.research_workspace import (
    WorkspaceProvisionError,
    WorkspaceWriteAuthorizationError,
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


class WritableBucketSimulator:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def bucket_info(self, bucket_id: str, *, token: str | None) -> None:
        pass

    def batch_bucket_files(self, *args: Any, **kwargs: Any) -> None:
        raise self.failure


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


def test_readable_workspace_id_takes_precedence_over_internal_session() -> None:
    assert (
        _session_id(
            {
                "request_session_id": "research-0d40b85945be",
                "research_workspace_id": "26-07-21-client-usage-a7d1",
            },
            {},
        )
        == "26-07-21-client-usage-a7d1"
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


def test_xet_write_forbidden_has_safe_actionable_error() -> None:
    api = WritableBucketSimulator(
        ConnectionError(
            "secret-native-detail: HTTP status client error (403 Forbidden), "
            "domain: https://huggingface.co/api/buckets/alice/research-agent/"
            "xet-write-token"
        )
    )

    with pytest.raises(WorkspaceWriteAuthorizationError) as caught:
        ensure_workspace(
            auth=auth(),
            request_metadata={"request_session_id": "chat"},
            open_metadata={},
            api=api,  # type: ignore[arg-type]
        )

    assert caught.value.code == "HF_BUCKET_WRITE_NOT_AUTHORIZED"
    assert "contribute-repos" in str(caught.value)
    assert "secret-native-detail" not in str(caught.value)
    assert isinstance(caught.value.__cause__, ConnectionError)


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("403 Forbidden at /xet-read-token"),
        ConnectionError("401 Unauthorized at /xet-write-token"),
        httpx.HTTPStatusError(
            "403 Forbidden at /xet-write-token",
            request=httpx.Request("GET", "https://huggingface.co"),
            response=httpx.Response(403),
        ),
    ],
)
def test_other_marker_failures_are_not_misclassified(failure: Exception) -> None:
    api = WritableBucketSimulator(failure)

    with pytest.raises(WorkspaceProvisionError) as caught:
        ensure_workspace(
            auth=auth(),
            request_metadata={"request_session_id": "chat"},
            open_metadata={},
            api=api,  # type: ignore[arg-type]
        )

    assert not isinstance(caught.value, WorkspaceWriteAuthorizationError)
    assert str(caught.value) == (
        "The research workspace could not be initialized. Reconnect your "
        "Hugging Face account and try again."
    )
    assert caught.value.__cause__ is failure
