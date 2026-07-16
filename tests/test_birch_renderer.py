from __future__ import annotations

import pytest

from research.birch_renderer import (
    _bucket_object_path,
    _claim_finalize_attempt,
    _prepare_html_draft,
    _sandbox_environment,
    _workspace_path,
    read_birch_skill_file,
)
from research.app_jobs import ResearchJob
from research.research_workspace import ResearchWorkspace


def workspace() -> ResearchWorkspace:
    return ResearchWorkspace(
        username="alice",
        session_id="research-abc123",
        bucket_id="alice/research-agent",
        root="hf://buckets/alice/research-agent/research-abc123/",
        scratch=("hf://buckets/alice/research-agent/research-abc123/scratch/"),
        output="hf://buckets/alice/research-agent/research-abc123/output/",
        bucket_created=False,
        marker_paths=(),
        bearer_token="secret",
    )


def test_workspace_paths_are_relative_to_exact_session_mount() -> None:
    current = workspace()

    assert (
        _workspace_path(
            current,
            f"{current.root}scratch/draft.html",
            directory="scratch",
        )
        == "scratch/draft.html"
    )
    assert (
        _workspace_path(current, "output/report.html", directory="output")
        == "output/report.html"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/output/report.html",
        "../output/report.html",
        "research-abc123/output/report.html",
        "scratch/report.html",
        "hf://buckets/alice/research-agent/other-session/output/report.html",
    ],
)
def test_output_path_rejects_ambiguous_or_cross_session_paths(path: str) -> None:
    with pytest.raises(ValueError):
        _workspace_path(workspace(), path, directory="output")


def test_sandbox_mounts_only_the_current_session_as_workspace() -> None:
    current = workspace()

    sandbox = _sandbox_environment(current)
    mount = sandbox._volume_mounts[0]

    assert mount.source == "alice/research-agent"
    assert mount.path == "research-abc123"
    assert mount.mount_path == "/workspace"
    assert not mount.read_only
    assert (
        _bucket_object_path(current, "output/report.html")
        == "research-abc123/output/report.html"
    )


def test_prepare_draft_repairs_fences_and_bare_style_marker() -> None:
    prepared = _prepare_html_draft(
        """```html
<!doctype html>
<html><head>__BIRCH_SYSTEM_CSS__</head>
<body><main class="page"></main></body></html>
```"""
    )

    assert not prepared.startswith("```")
    assert "<style data-birch-system>__BIRCH_SYSTEM_CSS__</style>" in prepared


def test_prepare_draft_rejects_partial_html() -> None:
    with pytest.raises(ValueError, match="complete HTML document"):
        _prepare_html_draft("<main>Partial</main>")


def test_restricted_skill_reader_reads_declared_files_only() -> None:
    assert "# Birch HTML" in read_birch_skill_file("SKILL.md")
    assert '<main class="page stack"' in read_birch_skill_file(
        "resources/template.html"
    )

    with pytest.raises(ValueError, match="cannot traverse"):
        read_birch_skill_file("../fast-agent.yaml")

    with pytest.raises(FileNotFoundError):
        read_birch_skill_file("recipes/missing.md")


def test_finalize_attempts_allow_two_corrections_then_stop() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")

    _claim_finalize_attempt(job)
    _claim_finalize_attempt(job)
    _claim_finalize_attempt(job)

    with pytest.raises(RuntimeError, match="retry limit reached"):
        _claim_finalize_attempt(job)
