from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from harness_chat import build_fast_agent, enforce_host_isolation
from harness_run import atomic_write, read_prompt, usage_from_atif


@pytest.mark.asyncio
async def test_harness_disables_host_shell() -> None:
    fast = build_fast_agent()
    async with fast.app.run():
        enforce_host_isolation(fast)
        assert fast.app.context.no_shell is True


def test_read_prompt_requires_nonempty_file(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("  Research this.  \n", encoding="utf-8")
    assert read_prompt(prompt) == "Research this."

    prompt.write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_prompt(prompt)


def test_atomic_write_replaces_content(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    atomic_write(output, '{"value": 1}\n')
    atomic_write(output, '{"value": 2}\n')
    assert json.loads(output.read_text(encoding="utf-8")) == {"value": 2}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_usage_from_atif_preserves_unknown_cost(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.atif.json"
    trajectory.write_text(
        json.dumps(
            {
                "agent": {
                    "model_name": "model",
                    "extra": {"provider": "hf"},
                },
                "final_metrics": {
                    "total_prompt_tokens": 100,
                    "total_completion_tokens": 25,
                    "total_cached_tokens": 40,
                    "total_cost_usd": None,
                    "extra": {
                        "total_reasoning_tokens": 10,
                        "total_tool_use_tokens": 5,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    assert usage_from_atif(trajectory) == {
        "provider": "hf",
        "model": "model",
        "prompt_tokens": 100,
        "uncached_prompt_tokens": 60,
        "completion_tokens": 25,
        "total_tokens": 125,
        "cached_tokens": 40,
        "reasoning_tokens": 10,
        "tool_use_prompt_tokens": 5,
        "cost_usd": None,
    }


def test_usage_from_atif_reports_known_cost(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.atif.json"
    trajectory.write_text(
        json.dumps(
            {
                "agent": {"model_name": "model"},
                "final_metrics": {
                    "total_prompt_tokens": 10,
                    "total_completion_tokens": 2,
                    "total_cost_usd": 0.0125,
                },
            }
        ),
        encoding="utf-8",
    )
    assert usage_from_atif(trajectory)["cost_usd"] == 0.0125
