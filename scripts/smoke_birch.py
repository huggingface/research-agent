#!/usr/bin/env python3
"""Validate or finalize one Birch draft without running the research agent."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from huggingface_hub import HfFileSystem

from research.app_jobs import ResearchJob, current_research_job
from research.birch_renderer import (
    SKILL_ROOT,
    _prepare_html_draft,
    finalize_birch_artifact,
)
from research.research_workspace import (
    current_research_workspace,
    ensure_workspace,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "session_id", help="Research session, for example research-abc123"
    )
    parser.add_argument("--draft", default="scratch/report.html")
    parser.add_argument("--output", default="output/report.html")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the production HF Sandbox finalizer and persist the output",
    )
    return parser.parse_args()


def workspace(session_id: str):
    return ensure_workspace(
        auth=None,
        request_metadata={"harness_session_id": session_id},
        open_metadata={},
        create_bucket=False,
        write_markers=False,
    )


def check_local(session_id: str, draft: str) -> int:
    active = workspace(session_id)
    source = f"{active.root}{draft}"
    filesystem = HfFileSystem(token=active.bearer_token)
    with filesystem.open(source, "r") as handle:
        prepared = _prepare_html_draft(handle.read())

    finisher = SKILL_ROOT / "scripts" / "finish_birch_html.py"
    checker = SKILL_ROOT / "scripts" / "check_birch_renderings.py"

    with tempfile.TemporaryDirectory(prefix="birch-smoke-") as temporary:
        root = Path(temporary)
        artifact = root / "report.html"
        report = root / "check.md"
        artifact.write_text(prepared)
        subprocess.run(
            [sys.executable, str(finisher), str(artifact)],
            check=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(checker),
                "--artifact",
                str(artifact),
                "--no-capture",
                "--out",
                str(root / "check.json"),
                "--markdown",
                str(report),
                "--screenshots-dir",
                str(root / "screenshots"),
            ],
            check=False,
        )
        print(report.read_text())
    print(f"Source: {source}")
    return result.returncode


async def finalize_live(session_id: str, draft: str, output: str) -> int:
    active = workspace(session_id)
    job = ResearchJob(id=session_id, topic="Birch smoke", owner_id=active.username)
    workspace_token = current_research_workspace.set(active)
    job_token = current_research_job.set(job)
    try:
        result = await finalize_birch_artifact(draft, output)
    finally:
        current_research_job.reset(job_token)
        current_research_workspace.reset(workspace_token)
    print(result)
    return 0


def main() -> int:
    args = parse_args()
    if args.live:
        return asyncio.run(finalize_live(args.session_id, args.draft, args.output))
    return check_local(args.session_id, args.draft)


if __name__ == "__main__":
    raise SystemExit(main())
