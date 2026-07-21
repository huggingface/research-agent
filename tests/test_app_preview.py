from __future__ import annotations

from design.preview_states import TOPIC, preview_snapshot
from research.app_ui import build_research_ui


def test_preview_states_render_with_bundled_prefab_without_live_actions() -> None:
    for state in ("running", "completed", "failed", "cancelled"):
        app = build_research_ui(TOPIC, preview_snapshot(state), live=False)
        wire = app.to_json()
        html = app.html(renderer_mode="bundled")

        assert wire["state"]["job"]["status"] == state
        assert "start_research" not in str(wire)
        assert "research_status" not in str(wire)
        assert str(wire).count("'type': 'Markdown'") >= 2
        assert "Research Dispatch" in html


def test_live_app_exposes_real_cancel_action() -> None:
    app = build_research_ui(TOPIC, preview_snapshot("running"))

    assert "cancel_research" in str(app.to_json())


def test_report_controls_are_present_but_disabled_during_reporting() -> None:
    snapshot = preview_snapshot("running")
    snapshot["phase"] = "reporting"

    wire = str(build_research_ui(TOPIC, snapshot, live=False).to_json())

    assert "Add to chat" in wire
    assert "Open report" in wire
    assert "job.status != 'completed'" in wire
