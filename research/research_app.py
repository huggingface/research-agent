"""Harness app wrapper for per-user research bucket instructions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from fast_agent import AgentRequest, AppOpenRequest, HarnessAppContext
from mcp.types import TextContent

try:
    from .archive_provisioning import ensure_archive_space
    from .research_workspace import (
        ResearchWorkspace,
        current_research_workspace,
        ensure_workspace,
    )
except ImportError:  # loaded as top-level module from the fast-agent home
    from research.archive_provisioning import ensure_archive_space
    from research.research_workspace import (
        ResearchWorkspace,
        current_research_workspace,
        ensure_workspace,
    )

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping


class ResearchHarnessApp:
    """Intercept opened harness sessions and wrap invocations."""

    def __init__(self, context: HarnessAppContext) -> None:
        self._default_app = context.default_app

    @asynccontextmanager
    async def open(self, request: AppOpenRequest | None = None) -> AsyncIterator[Any]:
        resolved = request or AppOpenRequest()
        async with self._default_app.open(resolved) as session:
            yield ResearchHarnessSession(session, resolved.metadata)


class ResearchHarnessSession:
    """Per-open-session wrapper that injects bucket instructions per request."""

    def __init__(self, session: Any, open_metadata: Mapping[str, object]) -> None:
        self._session = session
        self._open_metadata = dict(open_metadata)

    @property
    def agent_app(self) -> Any:
        return self._session.agent_app

    @property
    def env(self) -> Any:
        return self._session.env

    async def invoke(self, request: AgentRequest) -> Any:
        workspace = await asyncio.to_thread(
            ensure_workspace,
            auth=request.auth,
            request_metadata={
                **request.metadata,
                "request_session_id": request.session_id,
            },
            open_metadata=self._open_metadata,
        )
        workspace = await self._with_archive_space(workspace)
        forwarded = self._with_bucket_instructions(request, workspace)
        workspace_token = current_research_workspace.set(workspace)
        try:
            if workspace.bearer_token is None:
                return await self._session.invoke(forwarded)

            from fast_agent.mcp.auth.context import request_bearer_token

            auth_token = request_bearer_token.set(workspace.bearer_token)
            try:
                return await self._session.invoke(forwarded)
            finally:
                request_bearer_token.reset(auth_token)
        finally:
            current_research_workspace.reset(workspace_token)

    async def _with_archive_space(
        self,
        workspace: ResearchWorkspace,
    ) -> ResearchWorkspace:
        try:
            archive = await asyncio.to_thread(
                ensure_archive_space,
                username=workspace.username,
                bucket_id=workspace.bucket_id,
                token=workspace.bearer_token,
            )
        except Exception as exc:
            return replace(
                workspace,
                archive_status="error",
                archive_error=f"{type(exc).__name__}: {exc}",
            )
        return replace(
            workspace,
            archive_space_id=archive.space_id,
            archive_space_url=archive.space_url,
            archive_app_url=archive.app_url,
            archive_status=archive.status,
            archive_template_version=archive.template_version,
            archive_installed_version=archive.installed_version,
        )

    def _with_bucket_instructions(
        self, request: AgentRequest, workspace: ResearchWorkspace
    ) -> AgentRequest:
        instructions = "\n".join(
            [
                "Verified research workspace for this request:",
                f"- Hugging Face user: `{workspace.username}`",
                f"- Bucket: `{workspace.bucket_id}`",
                f"- Root: `{workspace.root}`",
                f"- Scratch/workings: `{workspace.scratch}`",
                f"- Final user-facing outputs: `{workspace.output}`",
                *(
                    [
                        f"- Report archive Space: `{workspace.archive_space_id}`",
                        f"- Report archive: {workspace.archive_space_url}",
                        f"- Archive app: {workspace.archive_app_url}",
                        f"- Archive status: `{workspace.archive_status}`",
                    ]
                    if workspace.archive_space_id
                    else []
                ),
                "The workspace was verified before this prompt was sent.",
                f"Hugging Face MCP authentication is verified for `{workspace.username}`.",
                "The same caller bearer token is forwarded to Hugging Face MCP tool calls.",
                "If authentication status must be reported, call `hf__hf_whoami`; do not infer it from cached server instructions.",
                "Write the final Markdown report to the bucket-relative path `output/report.md` unless the user requests another filename.",
                "That path is inside the verified Hugging Face bucket session, not the server's local filesystem.",
                "Use Hugging Face filesystem tools for bucket files. Never create `output/`, `scratch/`, or report artifacts in the local working directory.",
                "When you report a Hugging Face bucket artifact to the user, include both the `hf://` path and the accessible HTTPS URL.",
                "Convert `hf://buckets/<owner>/<bucket>/<path>` to `https://huggingface.co/buckets/<owner>/<bucket>/tree/<path>`.",
                f"Default report URL: `https://huggingface.co/buckets/{workspace.bucket_id}/tree/{workspace.session_id}/output/report.md`",
            ]
        )

        return replace(
            request,
            message=_prepend_text(request.message, instructions),
            metadata={
                **request.metadata,
                "research_username": workspace.username,
                "research_session_id": workspace.session_id,
                "research_bucket_id": workspace.bucket_id,
                "research_bucket_root": workspace.root,
                "research_scratch": workspace.scratch,
                "research_output": workspace.output,
                "research_marker_paths": list(workspace.marker_paths),
                "research_archive_space_id": workspace.archive_space_id,
                "research_archive_space_url": workspace.archive_space_url,
                "research_archive_app_url": workspace.archive_app_url,
                "research_archive_status": workspace.archive_status,
                "research_archive_template_version": (
                    workspace.archive_template_version
                ),
                "research_archive_installed_version": (
                    workspace.archive_installed_version
                ),
                "research_archive_error": workspace.archive_error,
            },
        )


def create_app(context: HarnessAppContext) -> ResearchHarnessApp:
    return ResearchHarnessApp(context)


def _prepend_text(message: Any, text: str) -> Any:
    content = list(message.content)
    content.insert(
        0,
        TextContent(
            type="text",
            text=f"{text}\n\nUser request follows.",
        ),
    )
    return message.model_copy(update={"content": content})
