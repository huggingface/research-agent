from __future__ import annotations

import json

import pytest

from research.app_ui import build_research_ui
from research.hf_design import HF_DESIGNS, HF_FONT_STYLESHEET


def test_completed_view_continues_in_chat_with_full_markdown() -> None:
    snapshot = {
        "job_id": "research-123",
        "status": "completed",
        "phase": "completed",
        "done": True,
        "topic": "A long research topic",
        "events": [],
        "activity_roll": [],
        "recent_summaries": [],
        "activity_summary": "The report is complete.",
        "event_count": 4,
        "elapsed": "01:23",
        "turn_count": 3,
        "cancellable": False,
        "markdown_report": "# Findings",
        "archive_space_url": (
            "https://huggingface.co/spaces/alice/research-agent"
        ),
        "archive_app_url": "https://alice-research-agent.hf.space",
        "archive_template_version": "1.0.0",
        "html_report_ready": True,
        "trace_path": None,
        "result": "Completed.",
        "error": None,
        "created_at": 1,
        "updated_at": 2,
    }

    app = build_research_ui(snapshot["topic"], snapshot, build_id="a1b2c3d4")
    payload = json.dumps(app.to_json())

    assert "a1b2c3d4" in payload
    assert "build a1b2c3d4" in payload
    assert "Research Dispatch" in payload
    assert "dispatch-sheet" in payload
    assert "activity_summary" in payload
    assert "recent_summaries" in payload
    assert "cancel_research" in payload
    assert "research_chat_context" in payload
    assert "updateContext" in payload
    assert "{{ $result.markdown }}" in payload
    assert "sendMessage" in payload
    assert "Add to chat" in payload
    assert "Preparing Markdown" in payload
    assert "Open HTML report" in payload
    assert "HTML report unavailable" in payload
    assert "Building HTML report" in payload
    assert "Markdown report" in payload
    assert "dispatch-archive-link" in payload
    assert "dispatch-archive-card" not in payload
    assert "https://huggingface.co/spaces/alice/research-agent" in payload
    assert "dispatch-markdown-body" in payload
    assert payload.index("dispatch-markdown-report") < payload.index(
        "dispatch-report-actions"
    )
    assert '"when": "{{ job.markdown_report }}"' in payload
    assert "openLink" in payload
    assert "Cancel this research run?" in payload
    assert "Briefing the researcher" in payload
    assert "Original query" in payload
    assert "Agent events" in payload
    assert "Hide log" in payload
    assert "Show log" in payload
    assert "chevron-up" in payload
    assert "chevron-down" in payload
    assert app.to_json()["state"]["event_log_expanded"] is False
    assert app.stylesheets is None
    assert "hf-design" not in payload


def test_short_query_does_not_offer_expansion() -> None:
    snapshot = {
        "job_id": "research-123",
        "status": "running",
        "phase": "researching",
        "done": False,
        "events": [],
        "activity_roll": [],
        "recent_summaries": [],
        "activity_summary": "Working.",
        "activity_source": "researcher/agent_loop",
        "event_count": 1,
        "elapsed": "00:01",
        "turn_count": 0,
        "cancellable": True,
        "markdown_report": None,
        "html_report_ready": False,
        "html_report_url": None,
        "trace_path": None,
    }

    app = build_research_ui("A short query", snapshot, live=False)

    assert app.to_json()["state"]["query_toggleable"] is False


@pytest.mark.parametrize("design", HF_DESIGNS)
def test_hugging_face_design_options_include_brand_and_fonts(design: str) -> None:
    snapshot = {
        "job_id": "research-123",
        "status": "running",
        "phase": "researching",
        "done": False,
        "events": [],
        "activity_roll": [],
        "recent_summaries": [],
        "activity_summary": "Working.",
        "activity_source": "researcher/agent_loop",
        "event_count": 1,
        "elapsed": "00:01",
        "turn_count": 0,
        "cancellable": True,
        "markdown_report": None,
        "html_report_ready": False,
        "html_report_url": None,
        "trace_path": None,
    }

    app = build_research_ui("A query", snapshot, live=False, design=design)
    payload = json.dumps(app.to_json())

    assert f"hf-{design}" in payload
    assert "Hugging Face" in payload
    assert "Researcher" in payload
    assert "data:image/svg+xml;base64," in payload
    assert "@media (max-width: 560px)" in payload
    assert app.stylesheets == [HF_FONT_STYLESHEET]


def test_unknown_hugging_face_design_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown design"):
        build_research_ui(
            "A query",
            {"job_id": "research-123"},
            live=False,
            design="unknown",  # type: ignore[arg-type]
        )
