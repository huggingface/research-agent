#!/usr/bin/env python3
"""Regenerate and finalize HTML for an existing research workspace."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from huggingface_hub import HfApi, HfFileSystem, get_token

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fast_agent import AgentAuth

from research.app_artifacts import finalize_bucket_html
from research.app_jobs import ResearchJob
from research.birch_renderer import generate_birch_report
from research.research_workspace import ResearchWorkspace

SAFE_WORKSPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


async def recover(workspace_id: str, attempt: int) -> None:
    if not SAFE_WORKSPACE.fullmatch(workspace_id):
        raise ValueError("Workspace id contains unsupported characters")
    if attempt < 1:
        raise ValueError("Attempt must be positive")

    token = get_token()
    if not token:
        raise RuntimeError("Authenticate with `hf auth login` before recovery")
    api = HfApi()
    username = str(api.whoami(token=token)["name"])
    bucket_id = f"{username}/research-agent"
    root = f"hf://buckets/{bucket_id}/{workspace_id}/"
    filesystem = HfFileSystem(token=token)
    report_uri = f"{root}output/report.md"
    if not filesystem.isfile(report_uri):
        raise FileNotFoundError(report_uri)

    attempt_root = f"{root}scratch/presentation/attempts/{attempt}"
    if filesystem.exists(attempt_root):
        raise FileExistsError(
            f"Presentation attempt {attempt} already exists: {attempt_root}"
        )

    with filesystem.open(report_uri, "rb") as report:
        markdown_before = bytes(report.read())
    workspace = ResearchWorkspace(
        username=username,
        session_id=workspace_id,
        bucket_id=bucket_id,
        root=root,
        scratch=f"{root}scratch/",
        output=f"{root}output/",
        bucket_created=False,
        marker_paths=(),
        bearer_token=token,
    )
    changed_markdown = False
    try:
        await generate_birch_report(workspace, attempt=attempt)
    finally:
        with filesystem.open(report_uri, "rb") as report:
            markdown_after = bytes(report.read())
        if markdown_after != markdown_before:
            changed_markdown = True
            with filesystem.open(report_uri, "wb") as report:
                report.write(markdown_before)
    if changed_markdown:
        raise RuntimeError(
            "Recovery changed the canonical Markdown report; the original "
            "report was restored and HTML was not finalized"
        )

    job = ResearchJob(
        id=workspace_id,
        workspace_id=workspace_id,
        topic="Recover HTML report",
        owner_id=f"huggingface:{username}",
        birch_finalize_attempts=attempt,
    )
    urls = finalize_bucket_html(
        job,
        AgentAuth.bearer(
            token,
            provider="huggingface",
            subject=username,
        ),
        ROOT / "research",
        required=True,
    )
    if urls is None:
        raise RuntimeError("HTML finalization did not return artifact URLs")
    print(urls[0])
    print(urls[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(recover(args.workspace, args.attempt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
