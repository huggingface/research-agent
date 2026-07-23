"""Representative research snapshots for standalone Prefab previews."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

TOPIC = (
    "Recent papers (2025–2026) that are good candidates for demonstrating "
    "reproducibility — papers with open code, open datasets, and clear "
    "experimental setups that can be independently re-run and verified."
)

_RECENT = [
    {
        "ts": 0,
        "elapsed": "02:58",
        "kind": "Report",
        "source": "agent/birch-html",
        "message": (
            "Rendered an HTML draft of the findings with a summary table of "
            "collections by category."
        ),
        "progress": None,
        "total": None,
    },
    {
        "ts": 0,
        "elapsed": "02:56",
        "kind": "Hugging Face",
        "source": "hf/hf_fs_write",
        "message": (
            "Wrote research notes and the raw API response to disk for later "
            "verification."
        ),
        "progress": None,
        "total": None,
    },
]

_BASE: dict[str, Any] = {
    "job_id": "research-preview",
    "topic": TOPIC,
    "headline": "Reproducible Papers Shortlist",
    "workspace_id": "26-07-21-reproducible-papers-shortlist-view",
    "status": "running",
    "phase": "researching",
    "events": _RECENT,
    "timeline_events": _RECENT,
    "recent_events": _RECENT,
    "activity_roll": [
        {
            "elapsed": "03:00",
            "kind": "Activity",
            "message": "research/agent_loop: step 15 (llm)",
        },
        {
            "elapsed": "03:00",
            "kind": "Activity",
            "message": "hf/hf_api_list: ok · 35 items · 412ms",
        },
        {
            "elapsed": "02:59",
            "kind": "Activity",
            "message": "hf/hf_fs_write: completed",
        },
        {
            "elapsed": "02:58",
            "kind": "Activity",
            "message": "agent/birch-html: rendered report draft",
        },
        {
            "elapsed": "02:57",
            "kind": "Activity",
            "message": "research/agent_loop: step 14 (tool)",
        },
        {
            "elapsed": "02:56",
            "kind": "Activity",
            "message": "hf/hf_fs_read: completed",
        },
    ],
    "recent_summaries": [
        {
            "elapsed": "02:58",
            "source": "agent/birch-html",
            "message": (
                "Rendered an HTML draft of the findings with a summary table "
                "of collections by category."
            ),
        },
        {
            "elapsed": "02:56",
            "source": "hf/hf_fs_write",
            "message": (
                "Wrote research notes and the raw API response to disk for "
                "later verification."
            ),
        },
    ],
    "event_count": 48,
    "elapsed_seconds": 180,
    "elapsed": "03:00",
    "activity_progress": 44,
    "activity_summary": (
        "Reading collection metadata for the unsloth organization and "
        "cross-checking each collection’s visibility flag so private and "
        "draft collections are excluded from the final count."
    ),
    "activity_summary_revision": 4,
    "activity_source": "research/agent_loop",
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
                "Research complete. unsloth has 35 public collections; both "
                "the written summary and the interactive HTML report are "
                "ready to review."
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
                "Request failed — the collections endpoint returned HTTP 429 "
                "(rate-limited) after three retries. The run stopped before "
                "a report could be produced."
            ),
            activity_source="hf/hf_api_list",
            activity_roll=[
                {
                    "elapsed": "03:07",
                    "kind": "Activity",
                    "message": "hf/hf_api_list: HTTP 429 (retry 3/3)",
                },
                {
                    "elapsed": "03:07",
                    "kind": "Activity",
                    "message": "research/agent_loop: aborted",
                },
                {
                    "elapsed": "03:06",
                    "kind": "Activity",
                    "message": "hf/hf_api_list: HTTP 429 (retry 2/3)",
                },
            ],
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
                "Research cancelled by the user. Partial notes and the session "
                "trace collected so far have been kept; no final report was "
                "produced."
            ),
            activity_roll=[
                {
                    "elapsed": "03:12",
                    "kind": "Activity",
                    "message": "research/agent_loop: cancelled by user",
                },
                {
                    "elapsed": "03:11",
                    "kind": "Activity",
                    "message": "agent/birch-html: rendered 96kb (draft)",
                },
                {
                    "elapsed": "03:10",
                    "kind": "Activity",
                    "message": "hf/hf_fs_write: completed",
                },
            ],
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
