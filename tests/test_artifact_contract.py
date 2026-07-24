from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fast_agent import AgentAuth
from research.app_jobs import ResearchJob
from research.artifact_contract import (
    safe_artifact_path,
    validate_stage_manifest,
    verify_research_handoff,
)


class ResearchHandoffSimulator:
    def __init__(self, manifest: dict[str, Any]) -> None:
        self.manifest = manifest

    def whoami(self, *, token: str) -> dict[str, str]:
        return {"name": "alice"}

    def download_bucket_files(
        self,
        bucket_id: str,
        files: list[tuple[str, Path]],
        **kwargs: Any,
    ) -> None:
        remote, local = files[0]
        assert remote.endswith("/scratch/research/manifest.json")
        local.write_text(json.dumps(self.manifest))

    def list_bucket_tree(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                path="research-123/output/report.md",
                size=100,
                type="file",
            ),
            SimpleNamespace(
                path="research-123/scratch/research/data/summary.json",
                size=42,
                type="file",
            ),
            SimpleNamespace(
                path="research-123/output/chart.png",
                size=1024,
                type="file",
            ),
        ]


def test_research_handoff_verifies_declared_durable_artifacts() -> None:
    manifest = {
        "schema_version": 1,
        "stage": "research",
        "status": "complete",
        "artifacts": [
            {"path": "output/report.md", "media_type": "text/markdown"},
            {
                "path": "scratch/research/data/summary.json",
                "media_type": "application/json",
            },
            {"path": "output/chart.png", "media_type": "image/png"},
        ],
    }
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")

    result = verify_research_handoff(
        job,
        AgentAuth.bearer("token"),
        api=ResearchHandoffSimulator(manifest),  # type: ignore[arg-type]
    )

    assert result == manifest


def test_research_manifest_cannot_escape_its_artifact_boundary() -> None:
    with pytest.raises(ValueError, match="outside the research boundary"):
        validate_stage_manifest(
            {
                "schema_version": 1,
                "stage": "research",
                "status": "complete",
                "artifacts": [{"path": "other/report.html"}],
            },
            stage="research",
            allowed_prefixes=("scratch/research/", "output/"),
        )


@pytest.mark.parametrize("path", ["/tmp/chart.png", "../output/report.md", ""])
def test_artifact_paths_must_be_workspace_relative(path: str) -> None:
    with pytest.raises(ValueError, match="workspace-relative"):
        safe_artifact_path(path)
