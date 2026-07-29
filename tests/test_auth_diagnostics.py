from __future__ import annotations

import httpx
import pytest
from fast_agent import AgentAuth

from research.auth_diagnostics import (
    AuthDiagnosticsMiddleware,
    diagnostic_snapshot,
)


@pytest.mark.asyncio
async def test_auth_diagnostics_compares_headers_without_exposing_tokens() -> None:
    async def app(scope, receive, send) -> None:
        snapshot = diagnostic_snapshot(
            AgentAuth.bearer(
                "selected-token",
                provider="huggingface",
                subject="alice",
                scopes=("read-mcp", "write-repos"),
            )
        )
        response = httpx.Response(200, json=snapshot)
        await send(
            {
                "type": "http.response.start",
                "status": response.status_code,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response.content,
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=AuthDiagnosticsMiddleware(app)),
        base_url="https://researcher.example",
        headers={
            "Authorization": "Bearer selected-token",
            "X-HF-Authorization": "Bearer other-token",
        },
    ) as client:
        response = await client.get("/")

    result = response.json()
    assert result["selectedCredential"] == "authorization"
    assert result["headerTokensMatch"] is False
    assert result["duplicateAuthorizationHeader"] is False
    assert result["scopes"] == ["read-mcp", "write-repos"]
    assert "selected-token" not in response.text
    assert "other-token" not in response.text
    assert "alice" not in response.text
