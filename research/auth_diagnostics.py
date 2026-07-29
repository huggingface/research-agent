"""Non-secret OAuth transport diagnostics for cross-client comparisons."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fast_agent import AgentAuth
from fastmcp import FastMCP
from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError
from starlette.types import ASGIApp, Receive, Scope, Send

_FINGERPRINT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class HeaderDiagnostics:
    authorization: str | None = None
    x_hf_authorization: str | None = None
    authorization_count: int = 0
    x_hf_authorization_count: int = 0


_headers: ContextVar[HeaderDiagnostics | None] = ContextVar(
    "research_auth_diagnostic_headers",
    default=None,
)


class AuthDiagnosticsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = [
            (key.decode("latin-1").lower(), value.decode("latin-1"))
            for key, value in scope.get("headers", [])
        ]
        authorization = [
            _bearer(value) for key, value in headers if key == "authorization"
        ]
        x_hf_authorization = [
            _bearer(value) for key, value in headers if key == "x-hf-authorization"
        ]
        token = _headers.set(
            HeaderDiagnostics(
                authorization=next(filter(None, authorization), None),
                x_hf_authorization=next(filter(None, x_hf_authorization), None),
                authorization_count=len(authorization),
                x_hf_authorization_count=len(x_hf_authorization),
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _headers.reset(token)


def register_oauth_diagnostics(mcp: FastMCP, get_auth: Any) -> None:
    @mcp.tool(
        name="oauth_diagnostics",
        description=(
            "Return non-secret OAuth transport diagnostics for comparing MCP "
            "clients. Use only when troubleshooting authentication."
        ),
    )
    def oauth_diagnostics() -> dict[str, Any]:
        auth = get_auth()
        snapshot = diagnostic_snapshot(auth)
        snapshot["whoamiAuthorization"] = _whoami_authorization(auth)
        return snapshot


def diagnostic_snapshot(auth: AgentAuth | None) -> dict[str, Any]:
    headers = _headers.get() or HeaderDiagnostics()
    selected = _fingerprint(auth.token if auth else None)
    authorization = _fingerprint(headers.authorization)
    x_hf_authorization = _fingerprint(headers.x_hf_authorization)
    return {
        "authorizationHeader": authorization is not None,
        "xHfAuthorizationHeader": x_hf_authorization is not None,
        "duplicateAuthorizationHeader": headers.authorization_count > 1,
        "duplicateXHfAuthorizationHeader": headers.x_hf_authorization_count > 1,
        "headerTokensMatch": (
            authorization == x_hf_authorization
            if authorization is not None and x_hf_authorization is not None
            else None
        ),
        "selectedCredential": _selected_source(
            selected,
            authorization,
            x_hf_authorization,
        ),
        "credentialFingerprint": selected,
        "provider": auth.provider if auth else None,
        "scopes": sorted(auth.scopes) if auth else [],
        "clientIdFingerprint": _fingerprint(auth.client_id if auth else None),
        "subjectFingerprint": _fingerprint(auth.subject if auth else None),
        "diagnosticInstance": _fingerprint("diagnostic-instance"),
        "versions": {
            package: _package_version(package)
            for package in (
                "fast-agent-mcp",
                "fastmcp",
                "huggingface-hub",
                "hf-xet",
            )
        },
    }


def _selected_source(
    selected: str | None,
    authorization: str | None,
    x_hf_authorization: str | None,
) -> str:
    if selected is None:
        return "none"
    matches_authorization = selected == authorization
    matches_x_hf = selected == x_hf_authorization
    if matches_authorization and matches_x_hf:
        return "both"
    if matches_authorization:
        return "authorization"
    if matches_x_hf:
        return "x-hf-authorization"
    return "unmatched"


def _bearer(value: str | None) -> str | None:
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hmac.new(
        _FINGERPRINT_KEY,
        value.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _whoami_authorization(auth: AgentAuth | None) -> dict[str, Any] | None:
    if auth is None or not auth.token:
        return None
    try:
        whoami = HfApi().whoami(token=auth.token)
    except (HfHubHTTPError, OSError):
        return {"available": False}
    authorization = whoami.get("auth")
    if not isinstance(authorization, dict):
        return {"available": False}
    access_token = authorization.get("accessToken")
    if not isinstance(access_token, dict):
        access_token = {}
    fine_grained = access_token.get("fineGrained")
    if not isinstance(fine_grained, dict):
        fine_grained = {}
    return {
        "available": True,
        "type": authorization.get("type"),
        "expiresInMinutes": _expires_in_minutes(authorization.get("expiresAt")),
        "accessTokenRole": access_token.get("role"),
        "fineGrainedCategories": sorted(fine_grained),
    }


def _expires_in_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((expires_at - datetime.now(UTC)).total_seconds() // 60))
