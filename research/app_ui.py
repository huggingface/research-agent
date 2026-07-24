"""Prefab UI for a research job."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from prefab_ui.actions import CloseOverlay, OpenLink, SetInterval, SetState, ShowToast
from prefab_ui.actions.mcp import CallTool, SendMessage, UpdateContext
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Button,
    Column,
    Dialog,
    Div,
    Heading,
    Image,
    If,
    Markdown,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.control_flow import ForEach
from prefab_ui.rx import RESULT, STATE

from .hf_design import (
    HF_DESIGN_CSS,
    HF_FONT_STYLESHEET,
    HF_LOGO_DATA_URI,
    HFDesign,
    design_css_class,
    validate_design,
)

BROADSHEET_CSS = """
.dispatch-app {
  --dispatch-accent: color-mix(in oklab, var(--warning) 68%, var(--foreground));
  --dispatch-live: color-mix(in oklab, var(--success) 76%, #4a8a63);
  --dispatch-panel: color-mix(in oklab, var(--card) 76%, var(--muted));
  width: 100%;
  min-height: 760px;
  display: flex;
  justify-content: center;
  background: var(--muted);
  color: var(--foreground);
}
.dispatch-sheet {
  width: min(100%, 800px);
  height: 760px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--background);
  box-shadow: 0 3px 12px color-mix(in oklab, var(--foreground) 10%, transparent);
}
.dispatch-header {
  flex: none;
  padding: 22px 36px 14px;
}
.dispatch-kicker,
.dispatch-section-label,
.dispatch-time,
.dispatch-source,
.dispatch-meta,
.dispatch-log-line,
.dispatch-query-toggle,
.dispatch-status {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.dispatch-topbar {
  min-width: 0;
  align-items: center;
}
.dispatch-kicker {
  flex: none;
  color: var(--dispatch-accent);
  font-size: 11px;
  letter-spacing: .14em;
  text-transform: uppercase;
}
.dispatch-status-controls {
  min-width: 0;
  margin-left: 10px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.dispatch-stats {
  min-width: 0;
  margin-left: auto;
  align-items: center;
  color: var(--muted-foreground);
}
.dispatch-stat {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  letter-spacing: .035em;
  text-transform: uppercase;
  white-space: nowrap;
}
.dispatch-status {
  min-height: 25px;
  padding: 4px 11px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: .03em;
}
.dispatch-status-running {
  background: color-mix(in oklab, var(--warning) 17%, var(--background));
  color: color-mix(in oklab, var(--warning) 46%, var(--foreground));
}
.dispatch-status-complete {
  background: color-mix(in oklab, var(--warning) 30%, var(--background));
  color: color-mix(in oklab, var(--warning) 28%, var(--foreground));
}
.dispatch-status-failed {
  border: 1px solid var(--muted-foreground);
  color: var(--muted-foreground);
}
.dispatch-status-cancelled {
  background: var(--muted);
  color: var(--muted-foreground);
}
.dispatch-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--dispatch-live);
  animation: dispatch-pulse 1.4s ease-in-out infinite;
}
.dispatch-header-separator {
  margin: 14px 0 16px;
}
.dispatch-query-row {
  min-width: 0;
  align-items: baseline;
}
.dispatch-section-label {
  flex: none;
  color: var(--muted-foreground);
  font-size: 10px;
  letter-spacing: .14em;
  text-transform: uppercase;
}
.dispatch-query-wrap {
  min-width: 0;
  flex: 1;
}
.dispatch-headline {
  margin: 0;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: clamp(26px, 4vw, 34px);
  font-weight: 500;
  line-height: 1.12;
  letter-spacing: -.02em;
  text-wrap: balance;
}
.dispatch-original-label {
  display: block;
  margin-top: 16px;
}
.dispatch-query {
  margin: 6px 0 0;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  color: var(--muted-foreground);
  font-size: 15px;
  font-weight: 400;
  line-height: 1.45;
  letter-spacing: 0;
  text-wrap: pretty;
}
.dispatch-query-clamped {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.dispatch-query-toggle {
  height: auto;
  min-height: 0;
  margin-top: 6px;
  padding: 0;
  color: var(--dispatch-accent);
  font-size: 11px;
  letter-spacing: .06em;
}
.dispatch-body {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0 36px;
  scrollbar-color: var(--muted-foreground) transparent;
  scrollbar-width: thin;
}
.dispatch-body::-webkit-scrollbar {
  width: 8px;
}
.dispatch-body::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: var(--muted-foreground);
}
.dispatch-report-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 0 22px;
}
.dispatch-report-action {
  width: 100%;
  color: var(--dispatch-accent);
}
.dispatch-markdown-report {
  margin-top: 16px;
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card);
}
.dispatch-markdown-body {
  margin-top: 14px;
  color: var(--foreground);
  font-size: 14px;
  line-height: 1.65;
}
.dispatch-markdown-body > :first-child {
  margin-top: 0;
}
.dispatch-markdown-body > :last-child {
  margin-bottom: 0;
}
.dispatch-log {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--dispatch-panel);
}
.dispatch-log-body {
  margin-top: 24px;
}
.dispatch-log-footer {
  margin: 0;
  padding-bottom: 0;
  border: 0;
  background: transparent;
}
.dispatch-log-line {
  min-width: 0;
  align-items: baseline;
  color: var(--muted-foreground);
  font-size: 12px;
  line-height: 1.35;
}
.dispatch-log-line + .dispatch-log-line {
  margin-top: 5px;
}
.dispatch-log-message {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-current-block {
  margin-top: 22px;
}
.dispatch-current-meta {
  align-items: baseline;
}
.dispatch-time {
  flex: none;
  color: var(--muted-foreground);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.dispatch-source {
  min-width: 0;
  overflow: hidden;
  color: var(--dispatch-accent);
  font-size: 11px;
  letter-spacing: .02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-current {
  margin-top: 9px;
  align-items: flex-start;
}
.dispatch-current-copy {
  max-width: 60ch;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: 22px;
  line-height: 1.34;
  letter-spacing: -.005em;
  text-wrap: pretty;
}
.dispatch-current-copy > :first-child,
.dispatch-event-message > :first-child {
  margin-top: 0;
}
.dispatch-current-copy > :last-child,
.dispatch-event-message > :last-child {
  margin-bottom: 0;
}
.dispatch-live-dot {
  position: relative;
  width: 11px;
  height: 11px;
  flex: none;
  margin-top: 8px;
  border-radius: 999px;
  background: var(--dispatch-live);
  animation: dispatch-pulse 1.4s ease-in-out infinite;
}
.dispatch-live-dot::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: inherit;
  animation: dispatch-ring 1.6s ease-out infinite;
}
.dispatch-rule {
  height: 2px;
  margin-top: 16px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--border);
}
.dispatch-rule-running::after {
  content: "";
  display: block;
  width: 40%;
  height: 100%;
  background: var(--dispatch-accent);
  animation: dispatch-progress 1.5s ease-in-out infinite;
}
.dispatch-rule-completed {
  background: var(--dispatch-accent);
}
.dispatch-rule-failed {
  height: 0;
  border-top: 2px dashed var(--muted-foreground);
  border-radius: 0;
  background: transparent;
}
.dispatch-rule-cancelled {
  background: color-mix(in oklab, var(--muted-foreground) 62%, transparent);
}
.dispatch-history {
  margin-top: 26px;
  padding-bottom: 26px;
}
.dispatch-event {
  min-width: 0;
  padding: 12px 0;
  border-top: 1px solid var(--border);
  opacity: .72;
}
.dispatch-event-copy {
  min-width: 0;
}
.dispatch-event-message {
  margin-top: 3px;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: 15px;
  line-height: 1.5;
  text-wrap: pretty;
}
.dispatch-read-confirmation {
  margin: -12px 0 18px;
  color: var(--muted-foreground);
  font-size: 11px;
}
.dispatch-footer {
  flex: none;
  border-top: 1px solid var(--border);
}
.dispatch-footer-log {
  padding: 8px 36px 0;
}
.dispatch-log-toggle {
  min-height: 24px;
  align-items: center;
}
.dispatch-log-toggle-button {
  height: auto;
  min-height: 0;
  margin-left: auto;
  padding: 2px 0;
  color: var(--muted-foreground);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  letter-spacing: .04em;
}
.dispatch-session {
  min-width: 0;
  padding: 12px 36px;
  align-items: center;
}
.dispatch-meta {
  flex: none;
  color: var(--muted-foreground);
  font-size: 11px;
  letter-spacing: .1em;
  text-transform: uppercase;
}
.dispatch-trace {
  min-width: 0;
  overflow: hidden;
  color: var(--muted-foreground);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-build {
  flex: none;
  margin-left: auto;
  color: var(--muted-foreground);
  font-size: 9px;
  opacity: .6;
}
.dispatch-archive-link {
  height: auto;
  min-height: 0;
  margin-left: auto;
  padding: 0;
  color: var(--muted-foreground);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}
.dispatch-archive-link + .dispatch-build {
  margin-left: 8px;
}
.dispatch-dialog-actions {
  margin-top: 8px;
  justify-content: flex-end;
}
@keyframes dispatch-progress {
  from { transform: translateX(-110%); }
  to { transform: translateX(250%); }
}
@keyframes dispatch-ring {
  from { transform: scale(1); opacity: .45; }
  to { transform: scale(2.6); opacity: 0; }
}
@keyframes dispatch-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .4; transform: scale(.78); }
}
@media (max-width: 720px) {
  .dispatch-sheet {
    border-right: 0;
    border-left: 0;
    border-radius: 0;
    box-shadow: none;
  }
  .dispatch-header {
    padding: 18px 20px 12px;
  }
  .dispatch-query-row {
    align-items: flex-start;
  }
  .dispatch-query-row {
    flex-direction: column;
  }
  .dispatch-query {
    margin-top: 8px;
    font-size: 14px;
  }
  .dispatch-body {
    padding: 0 20px;
  }
  .dispatch-log-footer {
    margin: 0;
  }
  .dispatch-footer-log {
    padding-right: 20px;
    padding-left: 20px;
  }
  .dispatch-session {
    padding: 12px 20px;
  }
  .dispatch-event {
    gap: 12px;
  }
  .dispatch-build {
    display: none;
  }
}
@media (max-width: 560px) {
  .dispatch-topbar {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .dispatch-stats {
    order: 3;
    width: 100%;
    margin: 9px 0 0;
  }
  .dispatch-status-controls {
    margin-left: auto;
  }
}
@media (max-width: 460px) {
  .dispatch-report-actions {
    grid-template-columns: 1fr;
  }
  .dispatch-status-controls {
    gap: 8px;
  }
  .dispatch-stats { justify-content: space-between; }
  .dispatch-current-copy {
    font-size: 20px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dispatch-live-dot,
  .dispatch-live-dot::after,
  .dispatch-status-dot,
  .dispatch-rule-running::after {
    animation: none;
  }
}
"""


def _display_source(source: str | None) -> str:
    return (source or "research/agent_loop").replace("/", " / ")


def _ui_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Add display-only fields without mutating the retained job snapshot."""
    prepared = deepcopy(snapshot)
    prepared.setdefault("headline", "Briefing the researcher")
    prepared.setdefault("workspace_id", None)
    prepared.setdefault(
        "activity_source_label", _display_source(prepared.get("activity_source"))
    )
    for summary in prepared.get("recent_summaries", []):
        summary.setdefault("source_label", _display_source(summary.get("source")))
    return prepared


def build_research_ui(
    topic: str,
    snapshot: dict[str, Any],
    *,
    build_id: str = "dev",
    live: bool = True,
    design: HFDesign | None = None,
) -> PrefabApp:
    snapshot = _ui_snapshot(snapshot)
    if design is not None:
        design = validate_design(design)
    on_mount = None
    if live:
        on_mount = [
            CallTool(
                "start_research",
                arguments={"job_id": STATE.job_id},
                on_success=[
                    SetState("job", RESULT),
                    SetState("poll_ms", RESULT.done.then("86400000", "1500")),
                ],
            ),
            SetInterval(
                duration=STATE.poll_ms,
                on_tick=CallTool(
                    "research_status",
                    arguments={"job_id": STATE.job_id},
                    on_success=[
                        SetState("job", RESULT),
                        SetState("poll_ms", RESULT.done.then("86400000", "1500")),
                    ],
                ),
            ),
        ]

    cancel_action = CloseOverlay()
    if live:
        cancel_action = CallTool(
            "cancel_research",
            arguments={"job_id": STATE.job_id},
            on_success=[
                SetState("job", RESULT),
                SetState("cancel_requested", False),
                CloseOverlay(),
                ShowToast(
                    "Cancellation requested",
                    description="The active research session is being closed.",
                    variant="warning",
                ),
            ],
            on_error=[
                SetState("cancel_requested", False),
                ShowToast(
                    "Could not cancel research",
                    description="The job may already have finished.",
                    variant="error",
                ),
            ],
        )

    read_report = CallTool(
        "research_chat_context",
        arguments={"job_id": STATE.job_id},
        on_success=[
            UpdateContext(content=RESULT.markdown),
            SendMessage(
                RESULT.message,
                on_success=SetState("chat_sent", True),
                on_error=ShowToast(
                    "This host could not send the chat message.",
                    variant="error",
                ),
            ),
        ],
        on_error=ShowToast(
            "Could not load the Markdown report.",
            variant="error",
        ),
    )
    if not live:
        read_report = SetState("chat_sent", True)

    css_class = "dispatch-app"
    css = [BROADSHEET_CSS]
    stylesheets = None
    if design is not None:
        css_class = design_css_class(design)
        css.append(HF_DESIGN_CSS)
        stylesheets = [HF_FONT_STYLESHEET]

    with PrefabApp(
        title="Research Dispatch",
        css_class=css_class,
        css=css,
        stylesheets=stylesheets,
        state={
            "job": snapshot,
            "topic": topic,
            "job_id": snapshot["job_id"],
            "poll_ms": "1500",
            "cancel_requested": False,
            "query_expanded": False,
            "query_toggleable": len(topic) > 90,
            "event_log_expanded": False,
            "chat_sent": False,
            "app_version": f"build {build_id}",
        },
    ) as ui:
        with Div(css_class="dispatch-sheet", on_mount=on_mount):
            with Column(css_class="dispatch-header", gap=0):
                with Row(css_class="dispatch-topbar", gap=4):
                    if design is None:
                        Text("Research Dispatch", css_class="dispatch-kicker")
                    else:
                        with Row(css_class="hf-brand", gap=2):
                            Image(
                                src=HF_LOGO_DATA_URI,
                                alt="Hugging Face",
                                css_class="hf-brand-logo",
                            )
                            with Column(css_class="hf-brand-copy", gap=0):
                                Text("Hugging Face", css_class="hf-brand-name")
                                Text(
                                    "Research Agent",
                                    css_class="hf-brand-product",
                                )
                    with Row(css_class="dispatch-stats", gap=2):
                        Text(STATE.job.elapsed, css_class="dispatch-stat")
                        Text("·", css_class="dispatch-stat")
                        Text(
                            "{{ job.event_count + ' events' }}",
                            css_class="dispatch-stat",
                        )
                        Text("·", css_class="dispatch-stat")
                        Text(
                            "{{ job.turn_count + ' turns' }}",
                            css_class="dispatch-stat",
                        )
                    with Row(css_class="dispatch-status-controls", gap=3):
                        with If(
                            (STATE.job.status == "queued")
                            | (STATE.job.status == "running")
                            | (STATE.job.status == "finalizing")
                            | (STATE.job.status == "cancelling")
                        ):
                            with Badge(
                                css_class=("dispatch-status dispatch-status-running")
                            ):
                                Div(css_class="dispatch-status-dot")
                                Text(
                                    "{{ job.status == 'cancelling' ? "
                                    "'Cancelling' : job.status == 'finalizing' ? "
                                    "'Finalizing' : job.phase == 'reporting' ? "
                                    "'Building report' : job.phase == 'wrapping_up' ? "
                                    "'Wrapping up' : 'Working' }}"
                                )
                        with If(STATE.job.status == "completed"):
                            Badge(
                                "Complete",
                                css_class=("dispatch-status dispatch-status-complete"),
                            )
                        with If(STATE.job.status == "failed"):
                            Badge(
                                "Failed",
                                variant="outline",
                                css_class=("dispatch-status dispatch-status-failed"),
                            )
                        with If(
                            (STATE.job.status == "cancelled")
                            | (STATE.job.status == "expired")
                        ):
                            Badge(
                                "{{ job.status == 'expired' ? "
                                "'Unavailable' : 'Cancelled' }}",
                                css_class=("dispatch-status dispatch-status-cancelled"),
                            )

                        with If(STATE.job.cancellable):
                            with Dialog(
                                title="Cancel this research run?",
                                description=(
                                    "The agent will stop where it is. Partial "
                                    "work and the session trace collected so far "
                                    "will be kept, but no final report will be "
                                    "produced."
                                ),
                            ):
                                Button("Cancel", variant="outline", size="sm")
                                with Row(css_class="dispatch-dialog-actions", gap=2):
                                    Button(
                                        "Keep running",
                                        variant="outline",
                                        onClick=CloseOverlay(),
                                    )
                                    Button(
                                        "Cancel research",
                                        variant="destructive",
                                        disabled=STATE.cancel_requested,
                                        onClick=[
                                            SetState("cancel_requested", True),
                                            cancel_action,
                                        ],
                                    )

                Separator(css_class="dispatch-header-separator")
                with Div(css_class="dispatch-query-wrap"):
                    Text("Research brief", css_class="dispatch-section-label")
                    Heading(
                        STATE.job.headline,
                        level=1,
                        css_class="dispatch-headline",
                    )
                    Text(
                        "Original query",
                        css_class=("dispatch-section-label dispatch-original-label"),
                    )
                    with Div():
                        with If(STATE.query_toggleable):
                            with If(~STATE.query_expanded):
                                Heading(
                                    STATE.topic,
                                    level=1,
                                    css_class="dispatch-query dispatch-query-clamped",
                                )
                                Button(
                                    "Show full query",
                                    variant="link",
                                    size="xs",
                                    css_class="dispatch-query-toggle",
                                    onClick=SetState("query_expanded", True),
                                )
                            with If(STATE.query_expanded):
                                Heading(
                                    STATE.topic,
                                    level=1,
                                    css_class="dispatch-query",
                                )
                                Button(
                                    "Show less",
                                    variant="link",
                                    size="xs",
                                    css_class="dispatch-query-toggle",
                                    onClick=SetState("query_expanded", False),
                                )
                        with If(~STATE.query_toggleable):
                            Heading(
                                STATE.topic,
                                level=1,
                                css_class="dispatch-query",
                            )

            with Div(css_class="dispatch-body"):
                with If(
                    STATE.job.markdown_report
                    | (STATE.job.phase == "reporting")
                    | (STATE.job.phase == "wrapping_up")
                    | (STATE.job.status == "finalizing")
                    | (STATE.job.status == "completed")
                ):
                    with If(STATE.job.markdown_report):
                        with Div(css_class="dispatch-markdown-report"):
                            Text(
                                "Markdown report",
                                css_class="dispatch-section-label",
                            )
                            Markdown(
                                STATE.job.markdown_report,
                                css_class="dispatch-markdown-body",
                            )
                    with Div(css_class="dispatch-report-actions"):
                        Button(
                            "{{ job.markdown_report ? 'Add to chat' : "
                            "'Preparing Markdown…' }}",
                            variant="outline",
                            css_class="dispatch-report-action",
                            disabled=(STATE.chat_sent | ~STATE.job.markdown_report),
                            onClick=read_report,
                        )
                        Button(
                            "{{ job.html_report_ready ? 'Open HTML report' : "
                            "job.done ? 'HTML report unavailable' : "
                            "'Building HTML report…' }}",
                            variant="outline",
                            css_class="dispatch-report-action",
                            disabled=~STATE.job.html_report_ready,
                            onClick=OpenLink(STATE.job.html_report_url),
                        )
                    with If(STATE.chat_sent):
                        Text(
                            "Added to chat.",
                            css_class="dispatch-read-confirmation",
                        )

                with If("{{ job.done && job.activity_roll.length > 0 }}"):
                    with Div(css_class="dispatch-log dispatch-log-body"):
                        with ForEach("job.activity_roll") as event:
                            with Row(css_class="dispatch-log-line", gap=3):
                                Text(event.elapsed, css_class="dispatch-time")
                                Text(
                                    event.message,
                                    css_class="dispatch-log-message",
                                )

                with Div(css_class="dispatch-current-block"):
                    with Row(css_class="dispatch-current-meta", gap=3):
                        Text(STATE.job.elapsed, css_class="dispatch-time")
                        Text(
                            STATE.job.activity_source_label,
                            css_class="dispatch-source",
                        )
                    with Row(css_class="dispatch-current", gap=3):
                        with If("{{ !job.done }}"):
                            Div(css_class="dispatch-live-dot")
                        Markdown(
                            STATE.job.activity_summary,
                            css_class="dispatch-current-copy",
                        )

                    with If("{{ !job.done }}"):
                        Div(css_class="dispatch-rule dispatch-rule-running")
                    with If(STATE.job.status == "completed"):
                        Div(css_class="dispatch-rule dispatch-rule-completed")
                    with If(STATE.job.status == "failed"):
                        Div(css_class="dispatch-rule dispatch-rule-failed")
                    with If(
                        (STATE.job.status == "cancelled")
                        | (STATE.job.status == "expired")
                    ):
                        Div(css_class="dispatch-rule dispatch-rule-cancelled")

                with If("{{ job.recent_summaries.length > 0 }}"):
                    with Div(css_class="dispatch-history"):
                        Text("Before this", css_class="dispatch-section-label")
                        with ForEach("job.recent_summaries") as event:
                            with Row(css_class="dispatch-event", gap=4):
                                Text(event.elapsed, css_class="dispatch-time")
                                with Column(css_class="dispatch-event-copy", gap=0):
                                    Text(
                                        event.source_label,
                                        css_class="dispatch-source",
                                    )
                                    Markdown(
                                        event.message,
                                        css_class="dispatch-event-message",
                                    )

            with Div(css_class="dispatch-footer"):
                with If("{{ !job.done && job.activity_roll.length > 0 }}"):
                    with Div(css_class="dispatch-footer-log"):
                        with Row(css_class="dispatch-log-toggle"):
                            Text("Agent events", css_class="dispatch-meta")
                            with If(STATE.event_log_expanded):
                                Button(
                                    "Hide log",
                                    icon="chevron-down",
                                    variant="link",
                                    size="xs",
                                    css_class="dispatch-log-toggle-button",
                                    onClick=SetState("event_log_expanded", False),
                                )
                            with If(~STATE.event_log_expanded):
                                Button(
                                    "Show log",
                                    icon="chevron-up",
                                    variant="link",
                                    size="xs",
                                    css_class="dispatch-log-toggle-button",
                                    onClick=SetState("event_log_expanded", True),
                                )
                        with If(STATE.event_log_expanded):
                            with Div(css_class="dispatch-log dispatch-log-footer"):
                                with ForEach("job.activity_roll") as event:
                                    with Row(css_class="dispatch-log-line", gap=3):
                                        Text(event.elapsed, css_class="dispatch-time")
                                        Text(
                                            event.message,
                                            css_class="dispatch-log-message",
                                        )
                with Row(css_class="dispatch-session", gap=3):
                    Text("Session", css_class="dispatch-meta")
                    Text(
                        "{{ job.trace_path || 'Trace pending' }}",
                        css_class="dispatch-trace",
                    )
                    with If(STATE.job.archive_space_url):
                        Button(
                            "Archive ↗",
                            variant="link",
                            size="xs",
                            css_class="dispatch-archive-link",
                            onClick=OpenLink(STATE.job.archive_space_url),
                        )
                    Text(STATE.app_version, css_class="dispatch-build")

    return ui
