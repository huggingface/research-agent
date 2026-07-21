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
    assert "Continue in chat" in payload
