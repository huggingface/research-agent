"""Run one Researcher Harness request from a UTF-8 file and export its usage."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fast_agent import AgentRequest, AppOpenRequest
from fast_agent.session import SessionTraceExporter
from fast_agent.session.session_manager import SessionManager
from fast_agent.session.trace_export_models import ExportRequest

from harness_chat import HERE, build_fast_agent, enforce_host_isolation
from research.app_auth import effective_agent_auth

DEFAULT_OUTPUT_ROOT = HERE / ".artifacts" / "local-runs"
RESEARCH_HOME = HERE / "research"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run one Researcher Harness request from a UTF-8 file.",
    )
    result.add_argument("input", type=Path, help="UTF-8 prompt file")
    result.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Run artifact directory root",
    )
    return result


def read_prompt(path: Path) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Input is not a file: {path}")
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Input is empty: {path}")
    return prompt


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
    temporary.replace(path)


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(HERE).as_posix()
    except ValueError:
        return str(resolved)


def usage_from_atif(path: Path) -> dict[str, Any]:
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    metrics = trajectory.get("final_metrics") or {}
    extra = metrics.get("extra") or {}
    prompt_tokens = metrics.get("total_prompt_tokens")
    completion_tokens = metrics.get("total_completion_tokens")
    cached_tokens = metrics.get("total_cached_tokens")
    uncached_prompt_tokens = (
        prompt_tokens - cached_tokens
        if isinstance(prompt_tokens, int)
        and isinstance(cached_tokens, int)
        and cached_tokens <= prompt_tokens
        else None
    )
    total_tokens = (
        prompt_tokens + completion_tokens
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int)
        else None
    )
    agent = trajectory.get("agent") or {}
    return {
        "provider": (agent.get("extra") or {}).get("provider"),
        "model": agent.get("model_name"),
        "prompt_tokens": prompt_tokens,
        "uncached_prompt_tokens": uncached_prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": extra.get("total_reasoning_tokens"),
        "tool_use_prompt_tokens": extra.get("total_tool_use_tokens"),
        "cost_usd": metrics.get("total_cost_usd"),
    }


async def invoke(prompt: str, session_id: str) -> str:
    sessions_dir = RESEARCH_HOME / "sessions"
    sessions_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sessions_dir.chmod(0o700)
    fast = build_fast_agent()
    auth = effective_agent_auth(None)
    metadata = {"requested_session_id": session_id}
    async with fast.harness() as harness:
        enforce_host_isolation(fast)
        with harness.request_context(auth=auth):
            async with harness.app().open(
                AppOpenRequest(
                    session_id=session_id,
                    agent="researcher",
                    metadata=metadata,
                )
            ) as session:
                response = await session.invoke(
                    AgentRequest.text(
                        prompt,
                        agent="researcher",
                        session_id=session_id,
                        auth=auth,
                        metadata=metadata,
                    )
                )
    return response.text_content()


def export_atif(session_id: str, output_path: Path) -> None:
    SessionTraceExporter(
        session_manager=SessionManager(home_override=RESEARCH_HOME),
    ).export(
        ExportRequest(
            target=session_id,
            agent_name="researcher",
            output_path=output_path,
            format="atif",
        )
    )
    output_path.chmod(0o600)


def main() -> int:
    args = parser().parse_args()
    prompt = read_prompt(args.input)
    session_id = f"file-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    run_dir = args.output_root.expanduser().resolve() / session_id
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "response.md"
    atif_path = run_dir / "trajectory.atif.json"
    summary_path = run_dir / "summary.json"
    session_dir = RESEARCH_HOME / "sessions" / session_id

    atomic_write(prompt_path, f"{prompt}\n")
    summary: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "session_id": session_id,
        "input": display_path(args.input),
        "artifacts": {
            "session_dir": display_path(session_dir),
            "prompt": display_path(prompt_path),
            "response": None,
            "atif": None,
            "summary": display_path(summary_path),
        },
        "usage": None,
        "error": None,
    }
    atomic_write(summary_path, f"{json.dumps(summary, indent=2)}\n")
    print(f"session: {session_id}", file=sys.stderr)
    print("research running; this may take several minutes", file=sys.stderr)

    failure: BaseException | None = None
    interrupted = False
    try:
        response = asyncio.run(invoke(prompt, session_id))
        atomic_write(response_path, f"{response.rstrip()}\n")
        summary["artifacts"]["response"] = display_path(response_path)
    except KeyboardInterrupt as exc:
        failure = exc
        interrupted = True
    except Exception as exc:
        failure = exc

    try:
        if session_dir.is_dir():
            export_atif(session_id, atif_path)
            summary["artifacts"]["atif"] = display_path(atif_path)
            summary["usage"] = usage_from_atif(atif_path)
    except Exception as exc:
        failure = failure or exc

    if interrupted:
        summary["status"] = "interrupted"
    elif failure is None:
        summary["status"] = "completed"
    else:
        summary["status"] = "failed"
        summary["error"] = {
            "type": type(failure).__name__,
            "message": str(failure),
        }
    atomic_write(summary_path, f"{json.dumps(summary, indent=2)}\n")
    print(json.dumps(summary, indent=2))
    if interrupted:
        return 130
    if failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
