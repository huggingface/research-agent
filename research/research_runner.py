"""The small, protocol-neutral fast-agent Harness integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fast_agent import AgentAuth, AgentRequest, AppOpenRequest
from fast_agent.llm.request_params import RequestParams

from .app_jobs import ResearchJob
from .app_observability import JobProgressHandler, try_export_trace

if TYPE_CHECKING:
    from fast_agent.core.harness import AgentHarness


class ResearchRunner:
    """Run one explicit job handle through a fast-agent Harness."""

    def __init__(self, harness: AgentHarness, home: Path) -> None:
        self.harness = harness
        self.home = home

    async def invoke(
        self,
        job: ResearchJob,
        auth: AgentAuth | None,
    ) -> str:
        """The essential Harness API flow used by this example."""
        with self.harness.request_context(auth=auth):
            async with self.harness.app().open(
                AppOpenRequest(
                    session_id=job.id,
                    agent="research",
                    metadata={"job_id": job.id},
                )
            ) as session:
                response = await session.invoke(
                    AgentRequest.text(
                        job.topic,
                        agent="research",
                        session_id=job.id,
                        auth=auth,
                        params=RequestParams(
                            tool_execution_handler=JobProgressHandler(job),
                            emit_loop_progress=True,
                        ),
                        metadata={"job_id": job.id},
                    )
                )
        return response.text_content()

    async def run(
        self,
        job: ResearchJob,
        auth: AgentAuth | None,
    ) -> None:
        """Add app lifecycle handling around the protocol-neutral invocation."""
        try:
            job.result = await self.invoke(job, auth)
            job.status = "finalizing"
            job.add_event("Research complete; exporting session trace")
            await try_export_trace(job, self.home)
            job.status = "completed"
            job.add_event("Research completed")
        except Exception as exc:
            job.error = str(exc)
            job.add_event(f"Research failed: {exc}", kind="error")
            await try_export_trace(job, self.home)
            job.status = "failed"
            job.add_event("Research job closed after failure", kind="error")
