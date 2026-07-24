"""Provision a private, versioned report-browser Space for one user."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from huggingface_hub import HfApi, Volume
from huggingface_hub.errors import RepositoryNotFoundError

ARCHIVE_TEMPLATE_SPACE = os.getenv(
    "RESEARCH_ARCHIVE_TEMPLATE_SPACE",
    "evalstate/research-archive-template",
)
ARCHIVE_TEMPLATE_VERSION = "1.1.0"
ARCHIVE_MARKER_PATH = "archive-template.json"
ARCHIVE_SPACE_NAME = "research-agent"
ARCHIVE_MOUNT_PATH = "/research"


class ArchiveProvisioningError(RuntimeError):
    """Archive Space could not be safely provisioned."""


class ArchiveSpaceCollisionError(ArchiveProvisioningError):
    """The desired Space name exists but is not managed by this application."""


@dataclass(frozen=True, slots=True)
class ArchiveProvisioning:
    space_id: str
    space_url: str
    app_url: str
    template_space: str
    template_version: str
    installed_version: str
    status: Literal["ready", "provisioning", "version_mismatch"]
    created: bool
    volume_updated: bool


def ensure_archive_space(
    *,
    username: str,
    bucket_id: str,
    token: str | None,
    api: HfApi | None = None,
    template_space: str = ARCHIVE_TEMPLATE_SPACE,
) -> ArchiveProvisioning:
    """Create or verify a user's managed archive Space and bucket mount."""
    expected_bucket = f"{username}/research-agent"
    if bucket_id != expected_bucket:
        raise ArchiveProvisioningError(
            f"Refusing to mount unexpected bucket {bucket_id!r}; "
            f"expected {expected_bucket!r}."
        )
    if not token:
        raise ArchiveProvisioningError(
            "A caller token is required to provision the archive Space."
        )

    api = api or HfApi()
    space_id = f"{username}/{ARCHIVE_SPACE_NAME}"
    desired_volume = Volume(
        type="bucket",
        source=bucket_id,
        mount_path=ARCHIVE_MOUNT_PATH,
        read_only=False,
    )
    created = False
    try:
        info = api.space_info(space_id, token=token)
    except RepositoryNotFoundError:
        template = _read_marker(api, template_space, token)
        _validate_template_marker(template, template_space)
        api.duplicate_repo(
            from_id=template_space,
            to_id=space_id,
            repo_type="space",
            private=True,
            exist_ok=True,
            space_hardware="cpu-basic",
            space_volumes=[desired_volume],
            space_variables=[
                {
                    "key": "RESEARCH_ARCHIVE_MANAGED",
                    "value": "true",
                    "description": "Managed by the Research Agent provisioner.",
                },
                {
                    "key": "RESEARCH_ARCHIVE_TEMPLATE_VERSION",
                    "value": ARCHIVE_TEMPLATE_VERSION,
                    "description": "Installed archive template version.",
                },
                {
                    "key": "RESEARCH_ARCHIVE_BUCKET",
                    "value": bucket_id,
                    "description": "Mounted Research Agent bucket.",
                },
            ],
            token=token,
        )
        created = True
        info = api.space_info(space_id, token=token)

    installed = _read_marker(api, space_id, token)
    _validate_managed_marker(installed, space_id)
    installed_version = str(installed["template_version"])

    volume_updated = not _has_expected_volume(info, bucket_id)
    if volume_updated:
        api.set_space_volumes(
            space_id,
            [desired_volume],
            token=token,
        )

    _ensure_variable(
        api,
        space_id,
        "RESEARCH_ARCHIVE_TEMPLATE_VERSION",
        installed_version,
        "Installed archive template version.",
        token,
    )
    _ensure_variable(
        api,
        space_id,
        "RESEARCH_ARCHIVE_BUCKET",
        bucket_id,
        "Mounted Research Agent bucket.",
        token,
    )

    status: Literal["ready", "provisioning", "version_mismatch"]
    if installed_version != ARCHIVE_TEMPLATE_VERSION:
        status = "version_mismatch"
    elif created or volume_updated:
        status = "provisioning"
    else:
        status = "ready"

    return ArchiveProvisioning(
        space_id=space_id,
        space_url=f"https://huggingface.co/spaces/{space_id}",
        app_url=f"https://{username}-{ARCHIVE_SPACE_NAME}.hf.space",
        template_space=template_space,
        template_version=ARCHIVE_TEMPLATE_VERSION,
        installed_version=installed_version,
        status=status,
        created=created,
        volume_updated=volume_updated,
    )


def _read_marker(api: HfApi, repo_id: str, token: str) -> dict[str, Any]:
    try:
        path = api.hf_hub_download(
            repo_id,
            ARCHIVE_MARKER_PATH,
            repo_type="space",
            token=token,
            force_download=True,
        )
        marker = json.loads(Path(path).read_text())
    except Exception as exc:
        raise ArchiveProvisioningError(
            f"Space {repo_id!r} has no readable {ARCHIVE_MARKER_PATH}."
        ) from exc
    if not isinstance(marker, dict):
        raise ArchiveProvisioningError(
            f"Space {repo_id!r} has an invalid {ARCHIVE_MARKER_PATH}."
        )
    return marker


def _validate_template_marker(marker: dict[str, Any], template_space: str) -> None:
    _validate_managed_marker(marker, template_space)
    version = str(marker.get("template_version", ""))
    if version != ARCHIVE_TEMPLATE_VERSION:
        raise ArchiveProvisioningError(
            f"Template {template_space!r} is version {version!r}; "
            f"the provisioner expects {ARCHIVE_TEMPLATE_VERSION!r}."
        )


def _validate_managed_marker(marker: dict[str, Any], space_id: str) -> None:
    if (
        marker.get("schema_version") != 1
        or marker.get("managed_by") != "research-agent"
        or marker.get("template") != "research-archive"
        or not marker.get("template_version")
    ):
        raise ArchiveSpaceCollisionError(
            f"Space {space_id!r} exists but is not a managed Research Archive."
        )


def _has_expected_volume(info: Any, bucket_id: str) -> bool:
    runtime = getattr(info, "runtime", None)
    raw = getattr(runtime, "raw", None)
    volumes = raw.get("volumes", []) if isinstance(raw, dict) else []
    return any(
        volume.get("type") == "bucket"
        and volume.get("source") == bucket_id
        and volume.get("mountPath") == ARCHIVE_MOUNT_PATH
        and not volume.get("readOnly", False)
        for volume in volumes
        if isinstance(volume, dict)
    )


def _ensure_variable(
    api: HfApi,
    space_id: str,
    key: str,
    value: str,
    description: str,
    token: str,
) -> None:
    variables = api.get_space_variables(space_id, token=token)
    current = variables.get(key)
    current_value = (
        current.value
        if hasattr(current, "value")
        else current.get("value")
        if isinstance(current, dict)
        else None
    )
    if current_value == value:
        return
    api.add_space_variable(
        space_id,
        key,
        value,
        description=description,
        token=token,
    )
