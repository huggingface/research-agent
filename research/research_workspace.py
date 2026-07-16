"""Resolve and prepare per-user Hugging Face bucket workspaces."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from huggingface_hub import HfApi, get_token
from huggingface_hub.errors import BucketNotFoundError

from fast_agent import AgentAuth
from fast_agent.mcp.server.common import normalize_serve_oauth_provider


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ResearchWorkspace:
    username: str
    session_id: str
    bucket_id: str
    root: str
    scratch: str
    output: str
    bucket_created: bool
    marker_paths: tuple[str, ...]
    bearer_token: str | None


def ensure_workspace(
    *,
    auth: AgentAuth | None,
    request_metadata: Mapping[str, Any],
    open_metadata: Mapping[str, object],
    create_bucket: bool = True,
    write_markers: bool = True,
    api: HfApi | None = None,
) -> ResearchWorkspace:
    """Resolve identity/session, ensure the bucket exists, and write markers."""
    token = _token(auth)
    whoami = _whoami(auth, token)
    username = _username(whoami)
    session_id = _session_id(request_metadata, open_metadata)
    bucket_id = f"{username}/research-agent"
    root = f"hf://buckets/{bucket_id}/{session_id}/"

    api = api or HfApi()
    bucket_created = False
    try:
        api.bucket_info(bucket_id, token=token)
    except BucketNotFoundError as exc:
        if not create_bucket:
            raise RuntimeError(
                f"Bucket {bucket_id!r} is not accessible: {exc}"
            ) from exc
        try:
            api.create_bucket(bucket_id, private=True, exist_ok=True, token=token)
            bucket_created = True
        except Exception as create_exc:
            raise RuntimeError(
                f"Could not create/access bucket {bucket_id!r}: {create_exc}"
            ) from create_exc

    marker_paths: tuple[str, ...] = ()
    if write_markers:
        marker = {
            "server": "research-agent",
            "username": username,
            "session_id": session_id,
            "bucket_id": bucket_id,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        try:
            api.batch_bucket_files(
                bucket_id,
                add=[
                    (
                        json.dumps(marker, indent=2).encode("utf-8"),
                        f"{session_id}/scratch/.workspace.json",
                    ),
                    (b"", f"{session_id}/output/.keep"),
                ],
                token=token,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Bucket {bucket_id!r} is accessible but marker write failed: {exc}"
            ) from exc
        marker_paths = (
            f"{root}scratch/.workspace.json",
            f"{root}output/.keep",
        )

    return ResearchWorkspace(
        username=username,
        session_id=session_id,
        bucket_id=bucket_id,
        root=root,
        scratch=f"{root}scratch/",
        output=f"{root}output/",
        bucket_created=bucket_created,
        marker_paths=marker_paths,
        bearer_token=token,
    )


def _token(auth: AgentAuth | None) -> str | None:
    if auth is not None and auth.token:
        return auth.token
    oauth_provider = normalize_serve_oauth_provider(os.getenv("FAST_AGENT_SERVE_OAUTH"))
    if oauth_provider == "huggingface":
        raise RuntimeError(
            "Hugging Face OAuth is enabled, but this request has no caller token."
        )
    env_token = os.getenv("HF_TOKEN")
    if env_token:
        return env_token
    return get_token()


def _whoami(auth: AgentAuth | None, token: str | bool | None) -> Mapping[str, Any]:
    """Return the authoritative Hugging Face whoami payload for this caller."""
    claims = dict(auth.claims) if auth is not None else {}
    whoami = claims.get("huggingface_whoami")
    if isinstance(whoami, dict) and whoami:
        return whoami

    try:
        return HfApi().whoami(token=token)
    except Exception as exc:
        raise RuntimeError(
            "Could not determine the Hugging Face user. Provide a bearer token, "
            "enable Hugging Face OAuth, set HF_TOKEN, or run `hf auth login`."
        ) from exc


def _username(whoami: Mapping[str, Any]) -> str:
    username = safe_segment(whoami.get("name"))
    if username:
        return username
    raise RuntimeError(
        f"Hugging Face whoami response did not include a usable name: {dict(whoami)!r}."
    )


def _session_id(
    request_metadata: Mapping[str, Any],
    open_metadata: Mapping[str, object],
) -> str:
    candidates = [
        request_metadata.get("request_session_id"),
        request_metadata.get("harness_session_id"),
        request_metadata.get("requested_session_id"),
        request_metadata.get("mcp_session_id"),
        open_metadata.get("harness_session_id"),
        open_metadata.get("requested_session_id"),
        open_metadata.get("mcp_session_id"),
    ]
    for candidate in candidates:
        value = safe_segment(candidate)
        if value:
            return value
    return "default"


def safe_segment(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("/")
    if not text:
        return None
    return _SAFE_SEGMENT.sub("-", text)[:96].strip(".-_") or None
