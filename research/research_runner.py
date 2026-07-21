"""The small, protocol-neutral fast-agent Harness integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fast_agent import AgentAuth, AgentRequest, AppOpenRequest
from fast_agent.llm.request_params import RequestParams

from .activity_narrator import ActivityNarrator, current_activity_narrator
from .app_auth import effective_agent_auth
from .app_artifacts import finalize_bucket_html
from .app_jobs import ResearchJob, current_research_job
from .app_observability import JobProgressHandler, try_export_trace

if TYPE_CHECKING:
    from fast_agent.core.harness import AgentHarness


class ResearchRunner:
    """Run one explicit job handle through a fast-agent Harness."""

    html_report_attempts = 2

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
            await self.build_html_report(job, auth)
            await try_export_trace(job, self.home)
            job.status = "completed"
            job.phase = "completed"
            job.set_activity_source("research/agent_loop")
            job.set_activity_summary(
                "Research complete. The written summary and interactive "
                "HTML report are ready to review."
            )
            job.add_event("Research completed")
        except asyncio.CancelledError:
            job.result = None
            job.error = None
            job.status = "cancelled"
            job.phase = "cancelled"
            job.set_activity_source("research/agent_loop")
            job.set_activity_summary(
                "Research cancelled by the user. Partial notes and the session "
                "trace collected so far have been kept; no final report was produced."
            )
            job.add_event("Research cancelled")
            await try_export_trace(job, self.home)
            raise
        except Exception as exc:
            job.error = str(exc)
            job.set_activity_summary(
                f"Research failed — {exc}. The run stopped before a final "
                "report could be produced."
            )
            job.add_event(f"Research failed: {exc}", kind="error")
            await try_export_trace(job, self.home)
            job.status = "failed"
            job.phase = "failed"
            job.add_event("Research job closed after failure", kind="error")

    async def build_html_report(
        self,
        job: ResearchJob,
        auth: AgentAuth | None,
    ) -> None:
        """Run and verify the mandatory delegated HTML stage with one retry."""
        auth = effective_agent_auth(auth)
        last_error: Exception | None = None

        for attempt in range(1, self.html_report_attempts + 1):
            job.birch_finalize_attempts = attempt
            job.status = "running"
            job.set_phase("reporting")
            job.add_event(
                f"Building interactive HTML report "
                f"(attempt {attempt}/{self.html_report_attempts})",
                kind="Report",
            )
            try:
                await self._invoke_html_agent(job, auth, attempt)
                job.set_phase("wrapping_up")
                job.status = "finalizing"
                urls = await self._finalize_html(job, auth)
                job.html_report_uri, job.html_report_url = urls
                if job.result and urls[0] not in job.result:
                    job.result += (
                        f"\n\n**Final HTML artifact:**\n- `{urls[0]}`\n- {urls[1]}"
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                job.add_event(
                    f"HTML report attempt {attempt} failed: {exc}",
                    kind="artifact",
                )

        raise RuntimeError(
            f"HTML report generation failed after {self.html_report_attempts} "
            f"attempts: {last_error}"
        ) from last_error

    async def _invoke_html_agent(
        self,
        job: ResearchJob,
        auth: AgentAuth,
        attempt: int,
    ) -> None:
        prompt = (
            "Build the required interactive HTML report for this Research "
            "Dispatch run. Read output/report.md from the verified workspace as "
            "the complete source of truth. Follow the Birch skill and canonical "
            "template. After the required reads, immediately call "
            "stage_birch_report with a concise structured brief preserving the "
            "key rankings, findings, caveats, and every distinct source URL. Do "
            "not explore other files or datasets, generate charts, call "
            "hf_fs_write, or draft HTML yourself. Return only the staged path "
            "and a concise note."
        )
        metadata = {
            "job_id": job.id,
            "report_stage": True,
            "report_attempt": attempt,
        }
        with self.harness.request_context(auth=auth):
            job_token = current_research_job.set(job)
            try:
                async with self.harness.app().open(
                    AppOpenRequest(
                        session_id=job.id,
                        agent="birch-html",
                        metadata=metadata,
                    )
                ) as session:
                    response = await session.invoke(
                        AgentRequest.text(
                            prompt,
                            agent="birch-html",
                            session_id=job.id,
                            auth=auth,
                            params=RequestParams(
                                tool_execution_handler=JobProgressHandler(job),
                                emit_loop_progress=True,
                            ),
                            metadata=metadata,
                        )
                    )
            finally:
                current_research_job.reset(job_token)
        if not response.text_content().strip():
            raise RuntimeError("Birch report agent returned an empty response")

    async def _finalize_html(
        self,
        job: ResearchJob,
        auth: AgentAuth,
    ) -> tuple[str, str]:
        urls = await asyncio.to_thread(
            finalize_bucket_html,
            job,
            auth,
            self.home,
            required=True,
        )
        if urls is None:  # defensive; required=True raises instead
            raise RuntimeError("Birch HTML finalizer returned no artifact")
        return urls
