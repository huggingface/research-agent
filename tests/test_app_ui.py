from __future__ import annotations

import json

from research.app_ui import build_research_ui


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
    assert "Open report" in payload
    assert "openLink" in payload
    assert "Cancel this research run?" in payload
    assert "Agent events" in payload
    assert "Hide log" in payload
    assert "Show log" in payload
    assert "chevron-up" in payload
    assert "chevron-down" in payload
    assert app.to_json()["state"]["event_log_expanded"] is True


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
        "activity_source": "research/agent_loop",
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
