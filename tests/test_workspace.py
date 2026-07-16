from __future__ import annotations

from typing import Any

import httpx
import pytest
from huggingface_hub.errors import BucketNotFoundError

from fast_agent import AgentAuth
from research.research_workspace import ensure_workspace


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
