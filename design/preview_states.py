"""Representative research snapshots for standalone Prefab previews."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

TOPIC = "How many collections does unsloth have?"

_RECENT = [
    {
        "ts": 0,
        "elapsed": "02:58",
        "kind": "Report",
        "message": (
            "The report writer finished a summary table of collections by category."
        ),
        "progress": None,
        "total": None,
    },
    {
        "ts": 0,
        "elapsed": "02:56",
        "kind": "Hugging Face",
        "message": (
            "The agent saved its research notes and source data for verification."
        ),
        "progress": None,
        "total": None,
    },
]

_BASE: dict[str, Any] = {
    "job_id": "research-preview",
    "topic": TOPIC,
    "status": "running",
    "phase": "reporting",
    "events": _RECENT,
    "timeline_events": _RECENT,
    "recent_events": _RECENT,
    "activity_roll": [
        {
            "elapsed": "03:00",
            "kind": "Activity",
            "message": "birch-html[1]/agent_loop: step 10 (llm)",
        },
        {
            "elapsed": "02:59",
            "kind": "Activity",
            "message": "agent/birch-html[1]: working",
        },
    ],
    "recent_summaries": [
        {
            "elapsed": "02:31",
            "message": (
                "The public collection list is verified, and the agent is "
                "checking visibility metadata before finalizing the count."
            ),
        },
        {
            "elapsed": "01:54",
            "message": (
                "The organization and collection endpoints are available; "
                "the agent is comparing their results."
            ),
        },
    ],
    "event_count": 48,
    "elapsed_seconds": 180,
    "elapsed": "03:00",
    "activity_progress": 44,
    "activity_summary": (
        "The research findings and Markdown report are complete. "
        "The HTML report is now being produced."
    ),
    "activity_summary_revision": 4,
    "activity_source": "birch-html[1]/agent_loop",
    "turn_count": 10,
    "result": None,
    "markdown_report": (
        "## Verified collection count\n\n"
        "The organization currently has **35 public collections**. The count "
        "excludes private and draft entries and was cross-checked against the "
        "collection metadata returned by the Hub.\n\n"
        "### Method\n\n"
        "The agent enumerated the public collection index, checked visibility "
        "metadata, and retained the source response for verification."
    ),
    "markdown_report_uri": (
        "hf://buckets/evalstate/research-agent/research-preview/output/report.md"
    ),
    "markdown_report_error": None,
    "html_report_uri": None,
    "html_report_url": None,
    "html_report_ready": False,
    "error": None,
    "trace_path": "~/research/sessions/research-preview/trace.jsonl",
    "trace_archive_uri": None,
    "trace_error": None,
    "done": False,
    "cancellable": True,
}


def preview_snapshot(state: str) -> dict[str, Any]:
    snapshot = deepcopy(_BASE)
    if state == "running":
        return snapshot
    if state == "completed":
        snapshot.update(
            status="completed",
            phase="completed",
            elapsed="03:23",
            elapsed_seconds=203,
            event_count=52,
            turn_count=11,
            activity_progress=100,
            activity_summary=(
                "Research complete. unsloth has 35 public collections; the "
                "written summary is ready to review."
            ),
            result=(
                "## Research complete\n\n"
                "unsloth has **35 public collections**. The report includes "
                "the verified count and linked sources."
            ),
            html_report_uri=(
                "hf://buckets/evalstate/research-agent/research-preview/"
                "output/report.html"
            ),
            html_report_url=(
                "https://huggingface.co/buckets/evalstate/research-agent/tree/"
                "research-preview/output/report.html"
            ),
            html_report_ready=True,
            done=True,
            cancellable=False,
        )
        return snapshot
    if state == "failed":
        snapshot.update(
            status="failed",
            phase="failed",
            elapsed="03:07",
            elapsed_seconds=187,
            event_count=29,
            turn_count=6,
            activity_progress=100,
            activity_summary=(
                "The collections endpoint remained rate-limited after three "
                "attempts, so the run stopped before a report was produced."
            ),
            error="The Hugging Face collections endpoint returned HTTP 429.",
            markdown_report=None,
            markdown_report_uri=None,
            html_report_uri=None,
            html_report_url=None,
            html_report_ready=False,
            done=True,
            cancellable=False,
        )
        return snapshot
    if state == "cancelled":
        snapshot.update(
            status="cancelled",
            phase="cancelled",
            elapsed="03:12",
            elapsed_seconds=192,
            event_count=41,
            turn_count=9,
            activity_progress=100,
            activity_summary=(
                "Research was cancelled. Partial notes and the session trace "
                "were kept; no final report was produced."
            ),
            markdown_report=None,
            markdown_report_uri=None,
            html_report_uri=None,
            html_report_url=None,
            html_report_ready=False,
            done=True,
            cancellable=False,
        )
        return snapshot
    raise ValueError(f"Unknown preview state: {state}")
