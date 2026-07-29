#!/usr/bin/env python3
"""Build self-contained Hugging Face Space deployment contexts."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".build" / "deploy"
IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.py[cod]",
    "*.db",
    ".check_for_update_done",
    ".gitignore",
    "fast-agent-log.jsonl",
    "logs",
    "output",
    "scratch",
    "sessions",
)


@dataclass(frozen=True)
class Overlay:
    source: str
    target: str


TARGETS = {
    "researcher": (
        Overlay("fastmcp_research_app.py", "fastmcp_research_app.py"),
        Overlay("research", "research"),
    ),
    "research-tool-one": (
        Overlay("research/research_app.py", "research_app.py"),
        Overlay("research/research_workspace.py", "research_workspace.py"),
        Overlay("research/__init__.py", "research/__init__.py"),
        Overlay("research/app_jobs.py", "research/app_jobs.py"),
        Overlay("research/app_observability.py", "research/app_observability.py"),
        Overlay("research/report_preview.py", "research/report_preview.py"),
        Overlay("research/archive_provisioning.py", "research/archive_provisioning.py"),
        Overlay("research/research_workspace.py", "research/research_workspace.py"),
        Overlay("research/skills/birch-html", "skills/birch-html"),
    ),
    "research-archive": (),
    "research-archive-template": (
        Overlay("deploy/research-archive/Dockerfile", "Dockerfile"),
        Overlay("deploy/research-archive/app.py", "app.py"),
        Overlay("deploy/research-archive/index.html", "index.html"),
        Overlay(
            "deploy/research-archive/huggingface-logo.svg",
            "huggingface-logo.svg",
        ),
        Overlay(
            "deploy/research-archive/archive-template.json",
            "archive-template.json",
        ),
    ),
}


def copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=IGNORE)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build(target_name: str, output_root: Path) -> Path:
    source = (ROOT / "deploy" / target_name).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Deployment source does not exist: {source}")

    target = (output_root / target_name).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError(f"Build output overlaps deployment source: {target}")
    shutil.rmtree(target, ignore_errors=True)
    copy(source, target)
    for overlay in TARGETS[target_name]:
        copy(ROOT / overlay.source, target / overlay.target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "targets",
        nargs="*",
        choices=TARGETS,
        default=None,
        metavar="TARGET",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    args = parser.parse_args()

    output_root = args.output.resolve()
    for target_name in args.targets or TARGETS:
        target = build(target_name, output_root)
        print(f"Built {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
