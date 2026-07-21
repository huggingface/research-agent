"""Prefab UI for a research job."""

from __future__ import annotations

from typing import Any

from prefab_ui.actions import SetInterval, SetState, ShowToast
from prefab_ui.actions.mcp import CallTool, SendMessage, UpdateContext
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Button,
    Column,
    Div,
    Heading,
    If,
    Markdown,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.control_flow import ForEach
from prefab_ui.rx import RESULT, STATE

BROADSHEET_CSS = """
.dispatch-app {
  min-height: 100%;
  padding: 24px;
  background: var(--muted);
  color: var(--foreground);
}
.dispatch-sheet {
  width: min(100%, 800px);
  min-height: 760px;
  margin: 0 auto;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--background);
  box-shadow: 0 12px 36px color-mix(in oklab, var(--foreground) 10%, transparent);
}
.dispatch-header {
  padding: 30px 36px 0;
}
.dispatch-kicker,
.dispatch-section-label,
.dispatch-time,
.dispatch-source,
.dispatch-meta,
.dispatch-trace {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.dispatch-kicker {
  color: color-mix(in oklab, var(--foreground) 58%, var(--warning));
  font-size: 11px;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.dispatch-controls {
  flex-wrap: wrap;
  justify-content: flex-end;
}
.dispatch-confirm {
  color: var(--muted-foreground);
  font-size: 12px;
}
.dispatch-section-label {
  color: var(--muted-foreground);
  font-size: 10px;
  letter-spacing: .15em;
  text-transform: uppercase;
}
.dispatch-query {
  max-width: 28ch;
  margin-top: 8px;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: clamp(22px, 3.5vw, 34px);
  font-weight: 500;
  line-height: 1.08;
  letter-spacing: -.025em;
  text-wrap: balance;
}
.dispatch-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 28px 36px 32px;
}
.dispatch-current-meta {
  gap: 14px;
  align-items: baseline;
}
.dispatch-run-stats {
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  color: var(--muted-foreground);
}
.dispatch-run-stat {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  letter-spacing: .035em;
  text-transform: uppercase;
}
.dispatch-activity-roll {
  margin-top: 15px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: color-mix(in oklab, var(--muted) 55%, transparent);
}
.dispatch-activity-line {
  gap: 12px;
  min-width: 0;
  align-items: baseline;
}
.dispatch-activity-line + .dispatch-activity-line {
  margin-top: 5px;
}
.dispatch-activity-message {
  min-width: 0;
  overflow: hidden;
  color: var(--muted-foreground);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-time {
  flex: none;
  color: var(--muted-foreground);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.dispatch-source {
  color: color-mix(in oklab, var(--foreground) 62%, var(--warning));
  font-size: 11px;
  letter-spacing: .025em;
}
.dispatch-current {
  margin-top: 12px;
  align-items: flex-start;
  gap: 14px;
}
.dispatch-current-copy {
  max-width: 62ch;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: clamp(18px, 2.8vw, 25px);
  line-height: 1.42;
  letter-spacing: -.012em;
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
  margin-top: 11px;
  border-radius: 999px;
  background: var(--success);
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
  margin-top: 20px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--border);
}
.dispatch-rule-running::after {
  content: "";
  display: block;
  width: 40%;
  height: 100%;
  background: var(--warning);
  animation: dispatch-progress 1.6s ease-in-out infinite;
}
.dispatch-rule-completed { background: var(--success); }
.dispatch-rule-failed {
  height: 0;
  border-top: 2px dashed var(--muted-foreground);
  background: transparent;
}
.dispatch-rule-cancelled { background: var(--muted-foreground); }
.dispatch-history {
  margin-top: 24px;
}
.dispatch-event {
  gap: 16px;
  padding: 13px 0;
  border-top: 1px solid var(--border);
  opacity: .76;
}
.dispatch-event-copy {
  min-width: 0;
}
.dispatch-event-message {
  margin-top: 4px;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.45;
  text-wrap: pretty;
}
.dispatch-result {
  margin-top: 28px;
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card);
}
.dispatch-report-markdown {
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
  font-size: 16px;
  line-height: 1.62;
  text-wrap: pretty;
}
.dispatch-result .dispatch-report-markdown h1 {
  margin: 8px 0 18px;
  font-size: clamp(25px, 4vw, 32px);
  font-weight: 500;
  line-height: 1.12;
  letter-spacing: -.022em;
  text-wrap: balance;
}
.dispatch-result .dispatch-report-markdown h2 {
  margin: 30px 0 12px;
  font-size: clamp(21px, 3vw, 25px);
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: -.012em;
}
.dispatch-result .dispatch-report-markdown h3 {
  margin: 24px 0 10px;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.3;
}
.dispatch-result .dispatch-report-markdown p,
.dispatch-result .dispatch-report-markdown li {
  line-height: 1.62;
}
.dispatch-result .dispatch-report-markdown strong {
  font-weight: 650;
}
.dispatch-result .dispatch-report-markdown hr {
  margin: 26px 0;
  border-color: var(--border);
}
.dispatch-result .dispatch-report-markdown code,
.dispatch-result .dispatch-report-markdown pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.dispatch-error {
  margin-top: 20px;
  color: var(--destructive);
  font-size: 13px;
}
.dispatch-footer {
  min-height: 44px;
  padding: 10px 36px;
  gap: 12px;
  align-items: center;
  border-top: 1px solid var(--border);
  color: var(--muted-foreground);
}
.dispatch-meta {
  flex: none;
  font-size: 11px;
  letter-spacing: .035em;
  font-variant-numeric: tabular-nums;
  text-transform: uppercase;
}
.dispatch-trace {
  min-width: 0;
  margin-left: auto;
  overflow: hidden;
  color: var(--muted-foreground);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@keyframes dispatch-progress {
  from { transform: translateX(-110%); }
  to { transform: translateX(250%); }
}
@keyframes dispatch-ring {
  from { transform: scale(1); opacity: .45; }
  to { transform: scale(2.5); opacity: 0; }
}
@media (max-width: 640px) {
  .dispatch-app { padding: 0; }
  .dispatch-sheet {
    min-height: 680px;
    border-right: 0;
    border-left: 0;
    border-radius: 0;
    box-shadow: none;
  }
  .dispatch-header { padding: 24px 22px 0; }
  .dispatch-body { padding: 24px 22px 28px; }
  .dispatch-footer {
    padding: 14px 22px;
    flex-wrap: wrap;
  }
  .dispatch-trace {
    width: 100%;
    margin-left: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dispatch-live-dot::after,
  .dispatch-rule-running::after {
    animation: none;
  }
}
"""


def build_research_ui(
    topic: str,
    snapshot: dict[str, Any],
    *,
    build_id: str = "dev",
    live: bool = True,
) -> PrefabApp:
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

    cancel_action = SetState("confirm_cancel", False)
    if live:
        cancel_action = CallTool(
            "cancel_research",
            arguments={"job_id": STATE.job_id},
            on_success=[
                SetState("job", RESULT),
                SetState("confirm_cancel", False),
                SetState("cancel_requested", False),
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

    with PrefabApp(
        title="Research Dispatch",
        css_class="dispatch-app",
        css=[BROADSHEET_CSS],
        state={
            "job": snapshot,
            "topic": topic,
            "job_id": snapshot["job_id"],
            "poll_ms": "1500",
            "confirm_cancel": False,
            "cancel_requested": False,
            "chat_sent": False,
            "app_version": f"build {build_id}",
        },
    ) as ui:
        with Div(css_class="dispatch-sheet", on_mount=on_mount):
            with Column(css_class="dispatch-header", gap=0):
                with Row(justify="between", align="start", gap=4):
                    Text("Research Dispatch", css_class="dispatch-kicker")
                    with Row(css_class="dispatch-controls", gap=2, align="center"):
                        Badge(STATE.app_version, variant="outline")
                        with If(
                            (STATE.job.status == "queued")
                            | (
                                (STATE.job.status == "running")
                                & (STATE.job.phase != "reporting")
                                & (STATE.job.phase != "wrapping_up")
                            )
                        ):
                            Badge("Working", variant="warning")
                        with If(
                            (STATE.job.status == "running")
                            & (STATE.job.phase == "reporting")
                        ):
                            Badge("Building report", variant="info")
                        with If(
                            (STATE.job.status == "running")
                            & (STATE.job.phase == "wrapping_up")
                        ):
                            Badge("Wrapping up", variant="warning")
                        with If(STATE.job.status == "finalizing"):
                            Badge("Finalizing", variant="warning")
                        with If(STATE.job.status == "completed"):
                            Badge("Complete", variant="success")
                        with If(STATE.job.status == "failed"):
                            Badge("Failed", variant="outline")
                        with If(STATE.job.status == "cancelled"):
                            Badge("Cancelled", variant="secondary")
                        with If(STATE.job.status == "cancelling"):
                            Badge("Cancelling", variant="warning")
                        with If(STATE.job.status == "expired"):
                            Badge("Unavailable", variant="secondary")
                        with If(STATE.job.cancellable & ~STATE.confirm_cancel):
                            Button(
                                "Cancel",
                                variant="ghost",
                                size="xs",
                                onClick=SetState("confirm_cancel", True),
                            )
                        with If(STATE.job.cancellable & STATE.confirm_cancel):
                            Text("Cancel research?", css_class="dispatch-confirm")
                            Button(
                                "Keep running",
                                variant="ghost",
                                size="xs",
                                onClick=SetState("confirm_cancel", False),
                            )
                            Button(
                                "Confirm",
                                variant="destructive",
                                size="xs",
                                disabled=STATE.cancel_requested,
                                onClick=[
                                    SetState("cancel_requested", True),
                                    cancel_action,
                                ],
                            )

                Separator(spacing=4)
                Text("Query", css_class="dispatch-section-label")
                Heading(STATE.topic, level=1, css_class="dispatch-query")

            with Div(css_class="dispatch-body"):
                with Row(css_class="dispatch-run-stats"):
                    Text(
                        "{{ 'Runtime ' + job.elapsed }}",
                        css_class="dispatch-run-stat",
                    )
                    Text("·", css_class="dispatch-run-stat")
                    Text(
                        "{{ job.event_count + ' events' }}",
                        css_class="dispatch-run-stat",
                    )
                    Text("·", css_class="dispatch-run-stat")
                    Text(
                        "{{ job.turn_count + ' agent turns' }}",
                        css_class="dispatch-run-stat",
                    )

                with If("{{ job.activity_roll.length > 0 }}"):
                    with Div(css_class="dispatch-activity-roll"):
                        with ForEach("job.activity_roll") as event:
                            with Row(css_class="dispatch-activity-line"):
                                Text(event.elapsed, css_class="dispatch-time")
                                Text(
                                    event.message,
                                    css_class="dispatch-activity-message",
                                )

                with Row(css_class="dispatch-current"):
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
                    (STATE.job.status == "cancelled") | (STATE.job.status == "expired")
                ):
                    Div(css_class="dispatch-rule dispatch-rule-cancelled")

                with If(STATE.job.markdown_report):
                    with Div(css_class="dispatch-result"):
                        with If(STATE.job.html_report_ready):
                            with Row(justify="between", align="center", gap=3):
                                Text(
                                    "Markdown report",
                                    css_class="dispatch-section-label",
                                )
                                Badge("HTML report produced", variant="success")
                        with If(
                            (STATE.job.phase == "reporting")
                            & ~STATE.job.html_report_ready
                        ):
                            Text(
                                "Markdown report · HTML version in progress",
                                css_class="dispatch-section-label",
                            )
                        with If(
                            (STATE.job.phase != "reporting")
                            & (STATE.job.phase != "wrapping_up")
                            & ~STATE.job.html_report_ready
                        ):
                            Text(
                                "Markdown report",
                                css_class="dispatch-section-label",
                            )
                        Markdown(
                            STATE.job.markdown_report,
                            css_class="dispatch-report-markdown",
                        )

                with If("{{ job.recent_summaries.length > 0 }}"):
                    with Div(css_class="dispatch-history"):
                        Text("Earlier updates", css_class="dispatch-section-label")
                        with ForEach("job.recent_summaries") as event:
                            with Row(css_class="dispatch-event", align="start"):
                                Text(event.elapsed, css_class="dispatch-time")
                                with Column(css_class="dispatch-event-copy", gap=0):
                                    Markdown(
                                        event.message,
                                        css_class="dispatch-event-message",
                                    )

                with If(STATE.job.error):
                    Text(STATE.job.error, css_class="dispatch-error")

                with If(STATE.job.result & ~STATE.job.markdown_report):
                    with Div(css_class="dispatch-result"):
                        Text("Final response", css_class="dispatch-section-label")
                        Markdown(STATE.job.result)

                with If(
                    (STATE.job.status == "completed") & ~STATE.chat_sent
                ):
                    Button(
                        "Continue in chat",
                        variant="outline",
                        size="sm",
                        onClick=CallTool(
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
                        ),
                    )
                with If(STATE.chat_sent):
                    Text(
                        "Report added to model context and sent to chat.",
                        css_class="dispatch-meta",
                    )

            with If(STATE.job.trace_path):
                with Row(css_class="dispatch-footer"):
                    Text(STATE.job.trace_path, css_class="dispatch-trace")

    return ui
