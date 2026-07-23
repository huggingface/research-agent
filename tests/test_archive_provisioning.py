from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from huggingface_hub.errors import RepositoryNotFoundError

from research.archive_provisioning import (
    ARCHIVE_TEMPLATE_VERSION,
    ArchiveProvisioningError,
    ArchiveSpaceCollisionError,
    ensure_archive_space,
)


class SpaceSimulator:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.markers = {
            "evalstate/research-archive-template": {
                "schema_version": 1,
                "managed_by": "research-agent",
                "template": "research-archive",
                "template_version": ARCHIVE_TEMPLATE_VERSION,
            }
        }
        self.spaces: dict[str, SimpleNamespace] = {}
        self.variables: dict[str, dict[str, SimpleNamespace]] = {}
        self.duplicate_calls = 0
        self.volume_calls = 0

    def space_info(self, repo_id: str, *, token: str) -> SimpleNamespace:
        if repo_id not in self.spaces:
            response = httpx.Response(
                404,
                request=httpx.Request(
                    "GET",
                    f"https://huggingface.co/api/spaces/{repo_id}",
                ),
            )
            raise RepositoryNotFoundError("missing", response=response)
        return self.spaces[repo_id]

    def duplicate_repo(
        self,
        *,
        from_id: str,
        to_id: str,
        space_variables: list[dict[str, str]],
        space_volumes: list[Any],
        **_: Any,
    ) -> None:
        self.duplicate_calls += 1
        self.markers[to_id] = dict(self.markers[from_id])
        self.spaces[to_id] = SimpleNamespace(
            runtime=SimpleNamespace(
                raw={
                    "volumes": [
                        {
                            "type": volume.type,
                            "source": volume.source,
                            "mountPath": volume.mount_path,
                            "readOnly": volume.read_only,
                        }
                        for volume in space_volumes
                    ]
                }
            )
        )
        self.variables[to_id] = {
            item["key"]: SimpleNamespace(value=item["value"])
            for item in space_variables
        }

    def hf_hub_download(self, repo_id: str, filename: str, **_: Any) -> str:
        assert filename == "archive-template.json"
        path = self.tmp_path / f"{repo_id.replace('/', '--')}.json"
        path.write_text(json.dumps(self.markers[repo_id]))
        return str(path)

    def set_space_volumes(
        self,
        repo_id: str,
        volumes: list[Any],
        *,
        token: str,
    ) -> None:
        self.volume_calls += 1
        self.spaces[repo_id].runtime.raw["volumes"] = [
            {
                "type": volume.type,
                "source": volume.source,
                "mountPath": volume.mount_path,
                "readOnly": volume.read_only,
            }
            for volume in volumes
        ]

    def get_space_variables(
        self,
        repo_id: str,
        *,
        token: str,
    ) -> dict[str, SimpleNamespace]:
        return self.variables.setdefault(repo_id, {})

    def add_space_variable(
        self,
        repo_id: str,
        key: str,
        value: str,
        **_: Any,
    ) -> None:
        self.variables.setdefault(repo_id, {})[key] = SimpleNamespace(value=value)


def test_provisioning_is_idempotent_and_copies_version_marker(tmp_path: Path) -> None:
    api = SpaceSimulator(tmp_path)

    first = ensure_archive_space(
        username="alice",
        bucket_id="alice/research-agent",
        token="caller-token",
        api=api,  # type: ignore[arg-type]
        template_space="evalstate/research-archive-template",
    )
    second = ensure_archive_space(
        username="alice",
        bucket_id="alice/research-agent",
        token="caller-token",
        api=api,  # type: ignore[arg-type]
        template_space="evalstate/research-archive-template",
    )

    assert first.created
    assert first.status == "provisioning"
    assert first.installed_version == ARCHIVE_TEMPLATE_VERSION
    assert second.status == "ready"
    assert not second.created
    assert api.duplicate_calls == 1
    assert api.volume_calls == 0
    assert api.markers["alice/research-agent"] == api.markers[
        "evalstate/research-archive-template"
    ]


def test_existing_unmanaged_space_is_not_overwritten(tmp_path: Path) -> None:
    api = SpaceSimulator(tmp_path)
    api.spaces["alice/research-agent"] = SimpleNamespace(
        runtime=SimpleNamespace(raw={"volumes": []})
    )
    api.markers["alice/research-agent"] = {
        "schema_version": 1,
        "managed_by": "someone-else",
        "template": "research-archive",
        "template_version": "1.0.0",
    }

    with pytest.raises(ArchiveSpaceCollisionError):
        ensure_archive_space(
            username="alice",
            bucket_id="alice/research-agent",
            token="caller-token",
            api=api,  # type: ignore[arg-type]
        )

    assert api.volume_calls == 0


def test_existing_version_mismatch_is_reported_without_overwrite(
    tmp_path: Path,
) -> None:
    api = SpaceSimulator(tmp_path)
    api.spaces["alice/research-agent"] = SimpleNamespace(
        runtime=SimpleNamespace(
            raw={
                "volumes": [
                    {
                        "type": "bucket",
                        "source": "alice/research-agent",
                        "mountPath": "/research",
                        "readOnly": False,
                    }
                ]
            }
        )
    )
    api.markers["alice/research-agent"] = {
        "schema_version": 1,
        "managed_by": "research-agent",
        "template": "research-archive",
        "template_version": "0.9.0",
    }

    result = ensure_archive_space(
        username="alice",
        bucket_id="alice/research-agent",
        token="caller-token",
        api=api,  # type: ignore[arg-type]
    )

    assert result.status == "version_mismatch"
    assert result.installed_version == "0.9.0"
    assert api.duplicate_calls == 0
    assert api.volume_calls == 0


def test_template_version_must_match_provisioner(tmp_path: Path) -> None:
    api = SpaceSimulator(tmp_path)
    api.markers["evalstate/research-archive-template"]["template_version"] = "2.0.0"

    with pytest.raises(ArchiveProvisioningError, match="expects"):
        ensure_archive_space(
            username="alice",
            bucket_id="alice/research-agent",
            token="caller-token",
            api=api,  # type: ignore[arg-type]
            template_space="evalstate/research-archive-template",
        )

    assert api.duplicate_calls == 0
