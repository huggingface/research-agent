"""Hugging Face OAuth wiring for the FastMCP server boundary."""

from __future__ import annotations

import os
from typing import Any, cast

from fast_agent import AgentAuth
from huggingface_hub import get_token
from fast_agent.mcp.auth.middleware import HFAuthHeaderMiddleware
from fast_agent.mcp.server import HarnessMCPAdapter
from fast_agent.mcp.server.common import (
    get_oauth_config,
    normalize_serve_oauth_provider,
)
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.huggingface import HuggingFaceTokenVerifier
from pydantic import AnyHttpUrl
from starlette.middleware import Middleware


def auth_provider() -> RemoteAuthProvider | None:
    provider, scopes, resource_url = get_oauth_config()
    if provider != "huggingface":
        return None
    return RemoteAuthProvider(
        token_verifier=HuggingFaceTokenVerifier(),
        authorization_servers=[AnyHttpUrl("https://huggingface.co")],
        base_url=AnyHttpUrl(resource_url),
        scopes_supported=scopes,
        resource_name="research-agent-app",
    )


def http_middleware() -> list[Middleware] | None:
    provider = normalize_serve_oauth_provider(os.environ.get("FAST_AGENT_SERVE_OAUTH"))
    if provider != "huggingface":
        return None
    return [Middleware(cast(Any, HFAuthHeaderMiddleware))]


def request_auth() -> AgentAuth | None:
    """Translate the current verified MCP token into fast-agent auth."""
    return HarnessMCPAdapter.agent_auth()


def effective_agent_auth(auth: AgentAuth | None) -> AgentAuth | None:
    """Use local credentials only when inbound Hugging Face OAuth is disabled."""
    if auth is not None and auth.token:
        return auth
    if (
        normalize_serve_oauth_provider(os.getenv("FAST_AGENT_SERVE_OAUTH"))
        == "huggingface"
    ):
        return auth
    token = os.getenv("HF_TOKEN") or get_token()
    return AgentAuth.bearer(token, provider="huggingface") if token else auth
