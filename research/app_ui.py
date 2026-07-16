"""Prefab UI for a research job."""

from __future__ import annotations

from typing import Any

from prefab_ui.actions import SetInterval, SetState
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Code,
    Column,
    Dot,
    Grid,
    Heading,
    If,
    Loader,
    Markdown,
    Metric,
    Muted,
    Progress,
    Row,
    Small,
    Text,
)
from prefab_ui.components.control_flow import Else, ForEach
from prefab_ui.rx import RESULT, STATE


def build_research_ui(topic: str, snapshot: dict[str, Any]) -> PrefabApp:
    with PrefabApp(
        state={
            "job": snapshot,
            "topic": topic,
            "job_id": snapshot["job_id"],
            "poll_ms": "1500",
        }
    ) as ui:
        with Column(
            gap=4,
            css_class="p-6",
            on_mount=[
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
            ],
        ):
            with Card(css_class="border-blue-200 bg-blue-50/40"):
                with CardContent():
                    with Row(justify="between", align="center", gap=4):
                        with Column(gap=1):
                            Heading("🤗 Research Agent")
                            Muted(STATE.topic)
                        with Row(gap=2, align="center"):
                            with If("{{ !job.done }}"):
                                Loader(variant="dots", size="sm")
                            Badge(STATE.job.status, variant="info")

            with Grid(columns={"default": 1, "lg": 3}, gap=4):
                with Card(css_class="lg:col-span-2"):
                    with CardHeader():
                        CardTitle("Timeline")
                        CardDescription(
                            "Latest 12 events; older events roll off the visible list."
                        )
                    with CardContent():
                        with Column(gap=2):
                            with ForEach("job.timeline_events") as event:
                                with Row(
                                    gap=3,
                                    align="start",
                                    css_class=(
                                        "rounded-md border border-border/60 "
                                        "bg-background px-3 py-2"
                                    ),
                                ):
                                    Dot(variant="info", size="sm", css_class="mt-1")
                                    Small(
                                        event.elapsed,
                                        code=True,
                                        css_class="min-w-12 text-muted-foreground",
                                    )
                                    Badge(event.kind, variant="outline")
                                    Text(
                                        event.message,
                                        css_class="text-sm leading-5",
                                    )

                with Column(gap=4):
                    with Card():
                        with CardHeader():
                            CardTitle("Activity")
                            CardDescription("Open-ended research task")
                        with CardContent():
                            with If("{{ !job.done }}"):
                                with Row(gap=3, align="center"):
                                    Loader(variant="bars", size="sm")
                                    Muted("Working")
                            with Else():
                                with Row(gap=3, align="center"):
                                    Badge(STATE.job.status, variant="outline")
                                    Muted("No active work")
                            Progress(
                                value=STATE.job.activity_progress,
                                max=100,
                                gradient=True,
                                size="sm",
                            )

                    with Grid(columns=2, gap=3):
                        with Card():
                            with CardContent():
                                Metric(label="Runtime", value=STATE.job.elapsed)
                        with Card():
                            with CardContent():
                                Metric(label="Events", value=STATE.job.event_count)

                    with If(STATE.job.trace_path):
                        with Card():
                            with CardHeader():
                                CardTitle("Session trace")
                            with CardContent():
                                Code(STATE.job.trace_path)

                    with If(STATE.job.trace_error):
                        with Card():
                            with CardHeader():
                                CardTitle("Trace export")
                            with CardContent():
                                Text(
                                    STATE.job.trace_error,
                                    css_class="text-amber-600",
                                )

            with If(STATE.job.error):
                with Card(css_class="border-red-200 bg-red-50/60"):
                    with CardHeader():
                        CardTitle("Unavailable")
                    with CardContent():
                        Text(STATE.job.error, css_class="text-red-700")

            with If(STATE.job.result):
                with Card():
                    with CardHeader():
                        CardTitle("Final result")
                        CardDescription("Generated report and summary")
                    with CardContent():
                        Markdown(
                            STATE.job.result,
                            css_class="whitespace-pre-wrap",
                        )

    return ui
