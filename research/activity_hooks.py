"""Declarative Tool Runner hooks for research activity narration."""

from __future__ import annotations

from fast_agent.hooks import HookContext

try:
    from .activity_narrator import activity_batch_from_hook, current_activity_narrator
except ImportError:  # loaded directly from the fast-agent home
    from research.activity_narrator import (
        activity_batch_from_hook,
        current_activity_narrator,
    )


async def capture_after_llm(ctx: HookContext) -> None:
    narrator = current_activity_narrator.get()
    if narrator is None:
        return
    try:
        narrator.observe(activity_batch_from_hook(ctx))
    except Exception:
        # Narration is presentation-only and must never affect the research loop.
        return
