"""Rolling fast-model narration for research activity."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any

from fast_agent.hooks import HookContext
from fast_agent.types.llm_stop_reason import LlmStopReason

from .app_jobs import ResearchJob

SummaryFunction = Callable[[str], Awaitable[str]]
Clock = Callable[[], float]

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|bearer|token|secret|password|api[_-]?key)",
    re.IGNORECASE,
)
_LARGE_VALUE_KEY = re.compile(
    r"(?:content|contents|blob|base64|data|file_data)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ActivityBatch:
    iteration: int
    stop_reason: str
    reasoning: str
    visible_text: str
    tool_calls: tuple[str, ...]

    @property
    def is_final(self) -> bool:
        return self.stop_reason != LlmStopReason.TOOL_USE.value


current_activity_narrator: ContextVar[ActivityNarrator | None] = ContextVar(
    "current_activity_narrator",
    default=None,
)


class ActivityNarrator:
    """Coalesce Tool Runner observations into a rolling user-facing narrative."""

    def __init__(
        self,
        job: ResearchJob,
        summarize: SummaryFunction,
        *,
        every_n_steps: int = 3,
        max_summary_age: float = 30,
        poll_interval: float = 5,
        timeout: float = 10,
        clock: Clock = monotonic,
    ) -> None:
        self.job = job
        self._summarize = summarize
        self._every_n_steps = max(1, every_n_steps)
        self._max_summary_age = max_summary_age
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._clock = clock

        self._latest: ActivityBatch | None = None
        self._revision = 0
        self._requested_revision = 0
        self._summarized_revision = 0
        self._steps_since_request = 0
        self._last_requested_at = clock()
        self._request_event = asyncio.Event()
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._worker: asyncio.Task[None] | None = None
        self._timer: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = asyncio.create_task(self._run(), name=f"{self.job.id}-narrator")
        self._timer = asyncio.create_task(
            self._run_timer(), name=f"{self.job.id}-narrator-timer"
        )

    def observe(self, batch: ActivityBatch) -> None:
        self.job.record_llm_step()
        if self.job.phase in {"reporting", "wrapping_up"}:
            return
        self._latest = batch
        self._revision += 1
        self._steps_since_request += 1

        first = self._summarized_revision == 0 and self._requested_revision == 0
        due_by_steps = self._steps_since_request >= self._every_n_steps
        if first or due_by_steps or batch.is_final:
            self.request_summary()

    def poll(self) -> None:
        """Request a summary when unsummarized activity has aged past the deadline."""
        has_unrequested_activity = self._revision > self._requested_revision
        due = self._clock() - self._last_requested_at >= self._max_summary_age
        if has_unrequested_activity and due:
            self.request_summary()

    def request_summary(self) -> None:
        if self._latest is None:
            return
        self._requested_revision = self._revision
        self._steps_since_request = 0
        self._last_requested_at = self._clock()
        self._idle_event.clear()
        self._request_event.set()

    async def close(self, *, flush_timeout: float = 12) -> None:
        if self._worker is None:
            return
        if self._revision > self._requested_revision:
            self.request_summary()
        if self._requested_revision > self._summarized_revision:
            try:
                await asyncio.wait_for(self._idle_event.wait(), timeout=flush_timeout)
            except TimeoutError:
                pass
        await self._cancel_tasks()

    async def _run(self) -> None:
        while True:
            await self._request_event.wait()
            self._request_event.clear()

            revision = self._requested_revision
            batch = self._latest
            if batch is None:
                self._idle_event.set()
                continue

            prompt = build_summary_prompt(
                topic=self.job.topic,
                previous_summary=self.job.activity_summary,
                batch=batch,
            )
            try:
                summary = await asyncio.wait_for(
                    self._summarize(prompt), timeout=self._timeout
                )
                summary = _clean_summary(summary)
            except asyncio.CancelledError:
                raise
            except Exception:
                if revision == self._requested_revision:
                    self._requested_revision = self._summarized_revision
                self._idle_event.set()
                continue

            if summary and revision >= self._summarized_revision:
                self._summarized_revision = revision
                self.job.set_activity_summary(self.job.narrative_for_phase(summary))

            if self._requested_revision > revision:
                self._request_event.set()
            else:
                self._idle_event.set()

    async def _run_timer(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            self.poll()

    async def _cancel_tasks(self) -> None:
        tasks = [task for task in (self._timer, self._worker) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._timer = None
        self._worker = None


def activity_batch_from_hook(ctx: HookContext) -> ActivityBatch:
    message = ctx.message
    stop_reason = (
        message.stop_reason.value if message.stop_reason is not None else "unknown"
    )
    return ActivityBatch(
        iteration=ctx.iteration,
        stop_reason=stop_reason,
        reasoning=_channel_text(message.channels, "reasoning", limit=1400),
        visible_text=_truncate(message.all_text().strip(), 700),
        tool_calls=tuple(_flatten_tool_calls(message.tool_calls)),
    )


def build_summary_prompt(
    *,
    topic: str,
    previous_summary: str,
    batch: ActivityBatch,
) -> str:
    tools = "\n".join(f"- {call}" for call in batch.tool_calls) or "- none"
    return "\n\n".join(
        [
            f"RESEARCH TASK\n{_truncate(topic, 600)}",
            f"PREVIOUS NARRATIVE\n{_truncate(previous_summary, 900) or '(none yet)'}",
            "\n".join(
                [
                    "LATEST ASSISTANT STEP",
                    f"Iteration: {batch.iteration}",
                    f"Stop reason: {batch.stop_reason}",
                    f"Exposed reasoning:\n{batch.reasoning or '(none)'}",
                    f"Visible response:\n{batch.visible_text or '(none)'}",
                    f"Tool calls:\n{tools}",
                ]
            ),
            (
                "Write the updated progress narrative now. Return only one or two "
                "short sentences. Describe what has been established and what is "
                "currently happening. Preserve uncertainty and tense; planned work "
                "is not completed work. Do not mention internal iterations, JSON, "
                "hooks, or framework details."
            ),
        ]
    )


def _channel_text(
    channels: Mapping[str, Any] | None,
    name: str,
    *,
    limit: int,
) -> str:
    blocks = (channels or {}).get(name) or []
    text = "\n".join(
        str(value).strip()
        for block in blocks
        if (value := getattr(block, "text", None))
    )
    return _truncate(text, limit)


def _flatten_tool_calls(tool_calls: Mapping[str, Any] | None) -> list[str]:
    flattened: list[str] = []
    for call in (tool_calls or {}).values():
        params = getattr(call, "params", None)
        name = str(getattr(params, "name", "tool"))
        arguments = _sanitize(getattr(params, "arguments", None) or {})
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        flattened.append(f"{name}: {_truncate(encoded, 700)}")
    return flattened[:8]


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "…"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:20]:
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                result[key] = "[redacted]"
            elif _LARGE_VALUE_KEY.fullmatch(key):
                result[key] = "[omitted]"
            else:
                result[key] = _sanitize(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return _truncate(value, 400)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _truncate(str(value), 400)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    marker = "\n…\n"
    half = (limit - len(marker)) // 2
    return f"{text[:half]}{marker}{text[-half:]}"


def _clean_summary(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    return _truncate(" ".join(text.split()), 500)
