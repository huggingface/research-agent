from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, TextContent

from fast_agent.hooks import HookContext
from fast_agent.mcp.prompt_message_extended import PromptMessageExtended
from fast_agent.types.llm_stop_reason import LlmStopReason
from research.activity_narrator import (
    ActivityBatch,
    ActivityNarrator,
    activity_batch_from_hook,
)
from research.app_jobs import ResearchJob


@dataclass
class RunnerSimulator:
    iteration: int = 2
    request_params: Any = None


@dataclass
class AgentSimulator:
    name: str = "research"
    message_history: list[Any] = None  # type: ignore[assignment]
    usage_accumulator: Any = None
    context: Any = None
    config: Any = None
    agent_registry: Any = None

    def __post_init__(self) -> None:
        self.message_history = []

    def load_message_history(self, messages: list[Any] | None) -> None:
        self.message_history = list(messages or [])

    def get_agent(self, name: str) -> None:
        del name
        return None


class ClockSimulator:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class SummarySimulator:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"Narrative {len(self.prompts)}"


async def wait_for_summaries(simulator: SummarySimulator, count: int) -> None:
    async with asyncio.timeout(1):
        while len(simulator.prompts) < count:
            await asyncio.sleep(0)


def batch(iteration: int, *, final: bool = False) -> ActivityBatch:
    return ActivityBatch(
        iteration=iteration,
        stop_reason=(
            LlmStopReason.END_TURN.value if final else LlmStopReason.TOOL_USE.value
        ),
        reasoning=f"Reasoning {iteration}",
        visible_text=f"Visible {iteration}",
        tool_calls=(f"tool_{iteration}: {{}}",) if not final else (),
    )


def test_hook_batch_flattens_reasoning_text_and_sanitized_tool_calls() -> None:
    message = PromptMessageExtended(
        role="assistant",
        content=[TextContent(type="text", text="I will inspect the repository.")],
        channels={
            "reasoning": [
                TextContent(
                    type="text",
                    text="I should verify the architecture against official sources.",
                )
            ]
        },
        tool_calls={
            "call-1": CallToolRequest(
                params=CallToolRequestParams(
                    name="hub_repo_details",
                    arguments={
                        "repo_ids": ["org/model"],
                        "token": "secret",
                        "content": "large payload",
                    },
                )
            )
        },
        stop_reason=LlmStopReason.TOOL_USE,
    )
    ctx = HookContext(
        runner=RunnerSimulator(),
        agent=AgentSimulator(),  # type: ignore[arg-type]
        message=message,
        hook_type="after_llm_call",
    )

    result = activity_batch_from_hook(ctx)

    assert result.iteration == 2
    assert "verify the architecture" in result.reasoning
    assert result.visible_text == "I will inspect the repository."
    assert "org/model" in result.tool_calls[0]
    assert "secret" not in result.tool_calls[0]
    assert "[redacted]" in result.tool_calls[0]
    assert "[omitted]" in result.tool_calls[0]


@pytest.mark.asyncio
async def test_narrator_triggers_first_every_n_and_final_steps() -> None:
    job = ResearchJob(id="job-1", topic="Topic", owner_id="alice")
    summary = SummarySimulator()
    narrator = ActivityNarrator(
        job,
        summary,
        every_n_steps=2,
        max_summary_age=30,
        poll_interval=60,
        clock=ClockSimulator(),
    )
    await narrator.start()
    try:
        narrator.observe(batch(0))
        await wait_for_summaries(summary, 1)

        narrator.observe(batch(1))
        await asyncio.sleep(0)
        assert len(summary.prompts) == 1

        narrator.observe(batch(2))
        await wait_for_summaries(summary, 2)

        narrator.observe(batch(3, final=True))
        await wait_for_summaries(summary, 3)
    finally:
        await narrator.close()

    assert job.activity_summary == "Narrative 3"
    assert job.activity_summary_revision == 3
    assert "PREVIOUS NARRATIVE\nNarrative 2" in summary.prompts[2]
    assert "Reasoning 3" in summary.prompts[2]


@pytest.mark.asyncio
async def test_narrator_wall_time_triggers_only_when_activity_is_pending() -> None:
    clock = ClockSimulator()
    job = ResearchJob(id="job-1", topic="Topic", owner_id="alice")
    summary = SummarySimulator()
    narrator = ActivityNarrator(
        job,
        summary,
        every_n_steps=10,
        max_summary_age=30,
        poll_interval=60,
        clock=clock,
    )
    await narrator.start()
    try:
        narrator.observe(batch(0))
        await wait_for_summaries(summary, 1)

        narrator.observe(batch(1))
        clock.now = 29
        narrator.poll()
        await asyncio.sleep(0)
        assert len(summary.prompts) == 1

        clock.now = 31
        narrator.poll()
        await wait_for_summaries(summary, 2)

        clock.now = 100
        narrator.poll()
        await asyncio.sleep(0)
        assert len(summary.prompts) == 2
    finally:
        await narrator.close()


@pytest.mark.asyncio
async def test_reporting_phase_overrides_stale_complete_narration() -> None:
    job = ResearchJob(id="job-1", topic="Topic", owner_id="alice")
    job.set_phase("reporting")
    summary = SummarySimulator()
    narrator = ActivityNarrator(job, summary, poll_interval=60)
    await narrator.start()
    try:
        narrator.observe(batch(0))
        await asyncio.sleep(0)
    finally:
        await narrator.close()

    assert not summary.prompts
    assert job.turn_count == 1
    assert job.activity_summary == (
        "The research findings and Markdown report are complete. "
        "The HTML report is now being produced."
    )
