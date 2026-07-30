"""The small, protocol-neutral fast-agent Harness integration."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fast_agent import AgentAuth, AgentRequest, AppOpenRequest
from fast_agent.llm.request_params import RequestParams
from huggingface_hub import HfApi

from .activity_narrator import ActivityNarrator, current_activity_narrator
from .app_auth import effective_agent_auth
from .app_artifacts import finalize_bucket_html
from .app_jobs import ResearchJob, current_research_job
from .app_observability import JobProgressHandler, try_export_trace
from .artifact_contract import verify_research_handoff
from .birch_renderer import generate_birch_report
from .research_workspace import ensure_workspace

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
        await self.prepare_identity(job, auth)

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
                        session_id=job.harness_session_id,
                        agent="researcher",
                        metadata={
                            "job_id": job.id,
                            "research_workspace_id": job.artifact_id,
                        },
                    )
                ) as session:
                    response = await session.invoke(
                        AgentRequest.text(
                            job.topic,
                            agent="researcher",
                            session_id=job.harness_session_id,
                            auth=auth,
                            params=RequestParams(
                                tool_execution_handler=JobProgressHandler(job),
                                emit_loop_progress=True,
                            ),
                            metadata={
                                "job_id": job.id,
                                "research_workspace_id": job.artifact_id,
                            },
                        )
                    )
            finally:
                current_research_job.reset(job_token)
                current_activity_narrator.reset(token)
                await narrator.close()
        await asyncio.to_thread(
            verify_research_handoff,
            job,
            auth,
        )
        job.add_event("Verified durable research handoff", kind="artifact")
        return response.text_content()

    async def prepare_identity(
        self,
        job: ResearchJob,
        auth: AgentAuth | None,
    ) -> None:
        """Name the brief before the research workspace is opened."""
        if job.workspace_id:
            return
        prompt = (
            "HEADLINE MODE\n\n"
            "Return only a specific 3–4 word headline for this research goal. "
            "Use title case and no punctuation. Avoid filler words such as "
            "Research, Analysis, Report, Study, or Overview. Do not include "
            "personal data, credentials, private identifiers, or repository "
            f"names.\n\nGOAL:\n{job.topic[:1200]}"
        )
        try:
            response = await self.harness.invoke(
                AgentRequest.text(
                    prompt,
                    agent="activity-summarizer",
                    session_id=f"{job.id}-headline",
                    auth=auth,
                    metadata={"job_id": job.id, "headline_generation": True},
                )
            )
            headline = _clean_headline(response.text_content())
        except Exception:
            headline = "Focused Research Brief"
        job.headline = headline
        job.workspace_id = _workspace_id(job, headline)
        job.add_event(f"Research brief named: {headline}", kind="Setup")

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
            job.set_activity_source("researcher/agent_loop")
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
            job.set_activity_source("researcher/agent_loop")
            job.set_activity_summary(
                "Research cancelled by the user. Partial notes and the session "
                "trace collected so far have been kept; no final report was produced."
            )
            job.add_event("Research cancelled")
            await try_export_trace(job, self.home)
            raise
        except Exception as exc:
            detail = _safe_error_message(exc)
            job.error = detail
            if job.markdown_report:
                job.set_activity_summary(
                    "The Markdown research report is ready, but the interactive "
                    f"HTML report could not be produced — {detail}."
                )
            else:
                job.set_activity_summary(
                    f"Research failed — {detail}. The run stopped before a final "
                    "report could be produced."
                )
            job.add_event(f"Research failed: {detail}", kind="error")
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
            workspace = None
            stage = "worker"
            job.birch_finalize_attempts = attempt
            job.status = "running"
            job.set_phase("reporting")
            job.add_event(
                f"Building interactive HTML report "
                f"(attempt {attempt}/{self.html_report_attempts})",
                kind="Report",
            )
            try:
                workspace = await self._invoke_html_agent(job, auth, attempt)
                stage = "finalization"
                job.set_phase("wrapping_up")
                job.status = "finalizing"
                urls = await self._finalize_html(job, auth)
                if workspace is not None:
                    await self._record_html_attempt(
                        job,
                        workspace,
                        attempt,
                        status="complete",
                    )
                job.html_report_uri, job.html_report_url = urls
                if job.result and urls[0] not in job.result:
                    job.result += (
                        f"\n\n**Final HTML artifact:**\n- `{urls[0]}`\n- {urls[1]}"
                    )
                return
            except asyncio.CancelledError as exc:
                if workspace is not None and stage == "finalization":
                    await asyncio.shield(
                        self._record_html_attempt(
                            job,
                            workspace,
                            attempt,
                            status="finalization-cancelled",
                            error=exc,
                        )
                    )
                raise
            except Exception as exc:
                detail = _safe_error_message(exc)
                last_error = RuntimeError(detail)
                if workspace is not None and stage == "finalization":
                    await self._record_html_attempt(
                        job,
                        workspace,
                        attempt,
                        status="finalization-failed",
                        error=exc,
                    )
                job.add_event(
                    f"HTML report attempt {attempt} failed: {detail}",
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
    ):
        workspace = await asyncio.to_thread(
            ensure_workspace,
            auth=auth,
            request_metadata={"research_workspace_id": job.artifact_id},
            open_metadata={},
            create_bucket=False,
            write_markers=False,
        )
        job.add_event(
            "Started isolated presentation sandbox with the workspace mounted",
            kind="Report",
        )
        job_token = current_research_job.set(job)
        await self._record_html_attempt(job, workspace, attempt, status="started")
        try:
            await generate_birch_report(workspace, attempt=attempt)
        except asyncio.CancelledError as exc:
            await self._record_html_attempt(
                job,
                workspace,
                attempt,
                status="cancelled",
                error=exc,
            )
            raise
        except Exception as exc:
            await self._record_html_attempt(
                job,
                workspace,
                attempt,
                status="failed",
                error=exc,
            )
            raise
        else:
            await self._record_html_attempt(
                job,
                workspace,
                attempt,
                status="worker-complete",
            )
        finally:
            current_research_job.reset(job_token)
        return workspace

    async def _record_html_attempt(
        self,
        job: ResearchJob,
        workspace,
        attempt: int,
        *,
        status: str,
        error: BaseException | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(
                _persist_html_attempt,
                workspace,
                attempt,
                status=status,
                error=error,
            )
        except Exception as exc:
            job.add_event(
                "Could not persist HTML attempt "
                f"{attempt} diagnostics: {_safe_error_message(exc)}",
                kind="artifact",
            )

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


def _clean_headline(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*", value.strip())
    if not 2 <= len(words) <= 6:
        return "Focused Research Brief"
    return " ".join(words[:4])


def _workspace_id(job: ResearchJob, headline: str) -> str:
    date = datetime.fromtimestamp(job.created_at, UTC).strftime("%y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:48]
    suffix = job.id.removeprefix("research-")[-4:]
    return f"{date}-{slug or 'research-brief'}-{suffix}"


def _persist_html_attempt(
    workspace,
    attempt: int,
    *,
    status: str,
    error: BaseException | None = None,
    api: HfApi | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "attempt": attempt,
        "status": status,
        "recorded_at": datetime.now(UTC).isoformat(),
        "error_type": type(error).__name__ if error else None,
        "error": _safe_error_message(error) if error else None,
    }
    (api or HfApi()).batch_bucket_files(
        workspace.bucket_id,
        add=[
            (
                json.dumps(payload, indent=2).encode(),
                (
                    f"{workspace.session_id}/scratch/presentation/"
                    f"attempts/{attempt}/attempt.json"
                ),
            )
        ],
        token=workspace.bearer_token,
    )


def _safe_error_message(error: BaseException) -> str:
    detail = str(error)
    patterns = (
        (r"(?i)(x-api-key\s*[:=]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(bearer\s+)\S+", r"\1<redacted>"),
        (r"\bhf_[A-Za-z0-9]{8,}\b", "<redacted-hf-token>"),
        (r"(://)[^/@\s]+@", r"\1<redacted>@"),
        (
            r"(?i)([?&](?:access_token|id_token|token|code|state|sig|signature|"
            r"api_key|password|secret|client_secret|x-amz-credential|"
            r"x-amz-security-token|x-amz-signature)=)[^&#\s]+",
            r"\1<redacted>",
        ),
        (
            r'(?i)(["\']?(?:access_token|id_token|token|api_key|password|secret|'
            r'client_secret)["\']?\s*[:=]\s*)'
            r'["\']?[^"\'\s,;}]+',
            r"\1<redacted>",
        ),
    )
    for pattern, replacement in patterns:
        detail = re.sub(pattern, replacement, detail)
    return detail[:4000]
