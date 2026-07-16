#!/usr/bin/env python3
"""Sync canonical Python sources into self-contained Space build contexts."""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIES = {
    "fastmcp_research_app.py": ("deploy/research-agent-two/fastmcp_research_app.py",),
    "research/__init__.py": ("deploy/research-agent-two/research/__init__.py",),
    "research/app_jobs.py": ("deploy/research-agent-two/research/app_jobs.py",),
    "research/app_auth.py": ("deploy/research-agent-two/research/app_auth.py",),
    "research/app_observability.py": (
        "deploy/research-agent-two/research/app_observability.py",
    ),
    "research/app_ui.py": ("deploy/research-agent-two/research/app_ui.py",),
    "research/fastmcp_server.py": (
        "deploy/research-agent-two/research/fastmcp_server.py",
    ),
    "research/research_app.py": (
        "deploy/research-agent-two/research/research_app.py",
        "deploy/research-tool-one/research_app.py",
    ),
    "research/research_workspace.py": (
        "deploy/research-agent-two/research/research_workspace.py",
        "deploy/research-tool-one/research_workspace.py",
    ),
    "research/research_runner.py": (
        "deploy/research-agent-two/research/research_runner.py",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report stale deployment copies without changing them.",
    )
    args = parser.parse_args()

    stale: list[str] = []
    for source_name, target_names in COPIES.items():
        source = ROOT / source_name
        for target_name in target_names:
            target = ROOT / target_name
            if target.exists() and filecmp.cmp(source, target, shallow=False):
                continue
            stale.append(target_name)
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    if stale:
        action = "Stale" if args.check else "Updated"
        print(f"{action} deployment copies:")
        print("\n".join(f"- {path}" for path in stale))
    return int(args.check and bool(stale))


if __name__ == "__main__":
    raise SystemExit(main())
