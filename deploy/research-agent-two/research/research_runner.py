"""The small, protocol-neutral fast-agent Harness integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fast_agent import AgentAuth, AgentRequest, AppOpenRequest
from fast_agent.llm.request_params import RequestParams

from .activity_narrator import ActivityNarrator, current_activity_narrator
from .app_auth import effective_agent_auth
from .app_jobs import ResearchJob, current_research_job
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
        auth = effective_agent_auth(auth)

        async def summarize_activity(prompt: str) -> str:
            response = await self.harness.invoke(
                AgentRequest.text(
                    prompt,
                    agent="activity-summarizer",
                    session_id=f"{job.id}-activity",
                    auth=auth,
                    metadata={"job_id": job.id, "activity_narrator": True},
                )
            )
            return response.text_content()

        narrator = ActivityNarrator(job, summarize_activity)
        with self.harness.request_context(auth=auth):
            await narrator.start()
            token = current_activity_narrator.set(narrator)
            job_token = current_research_job.set(job)
            try:
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
            finally:
                current_research_job.reset(job_token)
                current_activity_narrator.reset(token)
                await narrator.close()
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
            job.phase = "completed"
            job.add_event("Research completed")
        except asyncio.CancelledError:
            job.result = None
            job.error = None
            job.status = "cancelled"
            job.phase = "cancelled"
            job.set_activity_summary(
                "Research was cancelled. Partial notes and the session trace were kept."
            )
            job.add_event("Research cancelled")
            await try_export_trace(job, self.home)
            raise
        except Exception as exc:
            job.error = str(exc)
            job.add_event(f"Research failed: {exc}", kind="error")
            await try_export_trace(job, self.home)
            job.status = "failed"
            job.phase = "failed"
            job.add_event("Research job closed after failure", kind="error")
