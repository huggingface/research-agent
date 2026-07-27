from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.deploy_spaces import DEPLOYMENTS, create_space, wait_for_spaces


class SpaceApiSimulator:
    def __init__(self, *, sha: str, stage: str) -> None:
        self.sha = sha
        self.stage = stage

    def space_info(self, *args, **kwargs):
        return SimpleNamespace(
            sha=self.sha,
            runtime=SimpleNamespace(stage=self.stage),
        )


class SpaceCreationSimulator:
    def __init__(self) -> None:
        self.call = None

    def create_repo(self, *args, **kwargs) -> None:
        self.call = (args, kwargs)


def test_researcher_targets_clean_space() -> None:
    deployment = DEPLOYMENTS["researcher"]

    assert deployment.source == "researcher"
    assert deployment.repo_id == "evalstate/researcher"


def test_create_space_provisions_docker_sdk() -> None:
    api = SpaceCreationSimulator()

    create_space(api, DEPLOYMENTS["researcher"], token="token")

    assert api.call == (
        ("evalstate/researcher",),
        {
            "repo_type": "space",
            "space_sdk": "docker",
            "exist_ok": True,
            "token": "token",
        },
    )


def test_per_user_archive_reuses_canonical_archive_context() -> None:
    assert DEPLOYMENTS["research-agent-archive"].source == "research-archive"
    assert DEPLOYMENTS["research-agent-archive"].repo_id == (
        "evalstate/research-agent"
    )


def test_public_reports_reuses_canonical_archive_context() -> None:
    assert DEPLOYMENTS["researcher-reports"].source == "research-archive"
    assert DEPLOYMENTS["researcher-reports"].repo_id == (
        "evalstate/researcher-reports"
    )


def test_wait_accepts_exact_running_revision() -> None:
    wait_for_spaces(
        SpaceApiSimulator(sha="target", stage="RUNNING"),
        {"evalstate/space": "target"},
        token="token",
        timeout=0,
        poll_seconds=0,
    )


def test_wait_fails_on_target_revision_error() -> None:
    with pytest.raises(RuntimeError, match="BUILD_ERROR"):
        wait_for_spaces(
            SpaceApiSimulator(sha="target", stage="BUILD_ERROR"),
            {"evalstate/space": "target"},
            token="token",
            timeout=0,
            poll_seconds=0,
        )
