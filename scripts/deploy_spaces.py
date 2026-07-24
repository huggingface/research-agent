#!/usr/bin/env python3
"""Build, publish, and monitor named Hugging Face Space deployments."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, get_token

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_deploy import DEFAULT_OUTPUT, build  # noqa: E402

FAILURE_STAGES = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"}


@dataclass(frozen=True, slots=True)
class Deployment:
    source: str
    repo_id: str


DEPLOYMENTS = {
    "researcher": Deployment(
        "researcher",
        "evalstate/researcher",
    ),
    "research-tool-one": Deployment(
        "research-tool-one",
        "evalstate/research-tool-one",
    ),
    "research-archive": Deployment(
        "research-archive",
        "evalstate/research-archive",
    ),
    "research-archive-template": Deployment(
        "research-archive-template",
        "evalstate/research-archive-template",
    ),
    "research-agent-archive": Deployment(
        "research-archive",
        "evalstate/research-agent",
    ),
}


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
    ).strip()


def verify_source(*, allow_dirty: bool, allow_unpushed: bool) -> str:
    if not allow_dirty and git("status", "--porcelain"):
        raise RuntimeError("Refusing to deploy a dirty worktree; commit first.")
    sha = git("rev-parse", "HEAD")
    if not allow_unpushed:
        try:
            upstream = git("rev-parse", "@{upstream}")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Refusing to deploy without an upstream branch."
            ) from exc
        if sha != upstream:
            raise RuntimeError("Refusing to deploy an unpushed commit.")
    return sha


def wait_for_spaces(
    api: Any,
    revisions: dict[str, str],
    *,
    token: str,
    timeout: float,
    poll_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout
    last: dict[str, tuple[str | None, str | None]] = {}
    while True:
        pending: list[str] = []
        for repo_id, revision in revisions.items():
            info = api.space_info(
                repo_id,
                token=token,
                expand=["runtime", "sha"],
            )
            stage = info.runtime.stage if info.runtime else None
            state = (info.sha, stage)
            if last.get(repo_id) != state:
                print(f"{repo_id}: {info.sha} {stage}", flush=True)
                last[repo_id] = state
            if info.sha == revision and stage == "RUNNING":
                continue
            if info.sha == revision and stage in FAILURE_STAGES:
                raise RuntimeError(f"{repo_id} deployment failed: {stage}")
            pending.append(repo_id)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for: {', '.join(pending)}")
        time.sleep(poll_seconds)


def create_space(api: Any, deployment: Deployment, *, token: str) -> None:
    api.create_repo(
        deployment.repo_id,
        repo_type="space",
        space_sdk="docker",
        exist_ok=True,
        token=token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "deployments",
        nargs="+",
        choices=DEPLOYMENTS,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Build root (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    parser.add_argument("--message", help="Space commit message")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create missing Docker Spaces before upload.",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--allow-unpushed", action="store_true")
    args = parser.parse_args()

    source_sha = verify_source(
        allow_dirty=args.allow_dirty,
        allow_unpushed=args.allow_unpushed,
    )
    token = get_token()
    if not token:
        raise RuntimeError("Hugging Face authentication is required.")

    names = list(dict.fromkeys(args.deployments))
    contexts: dict[str, Path] = {}
    for name in names:
        source = DEPLOYMENTS[name].source
        if source not in contexts:
            contexts[source] = build(source, args.output.resolve())

    message = args.message or f"Deploy {source_sha[:7]}"
    api = HfApi()
    revisions: dict[str, str] = {}
    for name in names:
        deployment = DEPLOYMENTS[name]
        if args.create:
            create_space(api, deployment, token=token)
        commit = api.upload_folder(
            repo_id=deployment.repo_id,
            repo_type="space",
            folder_path=contexts[deployment.source],
            commit_message=message,
            commit_description=f"Source commit: {source_sha}",
            token=token,
        )
        revisions[deployment.repo_id] = commit.oid
        print(f"{deployment.repo_id}: {commit.commit_url}")

    if not args.no_wait:
        wait_for_spaces(
            api,
            revisions,
            token=token,
            timeout=args.timeout,
            poll_seconds=args.poll_seconds,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
