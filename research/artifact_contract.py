"""Durable artifact handoffs between ephemeral research sandboxes."""

from __future__ import annotations

import json
import posixpath
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from huggingface_hub import HfApi

from fast_agent import AgentAuth

from .app_jobs import ResearchJob

SCHEMA_VERSION = 1
RESEARCH_MANIFEST = "scratch/research/manifest.json"
MAX_MANIFEST_ARTIFACTS = 128
EMBEDDABLE_FIGURE_TYPES = {
    "image/jpeg": {".jpeg", ".jpg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}
MARKDOWN_IMAGE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<(?P<angle>[^>]+)>|(?P<plain>[^)\s]+))",
)


def verify_research_handoff(
    job: ResearchJob,
    auth: AgentAuth | None,
    *,
    api: HfApi | None = None,
) -> dict[str, Any]:
    """Verify the durable research handoff before presentation begins."""
    if auth is None or not auth.token:
        raise RuntimeError("Caller authentication is required to verify artifacts")

    api = api or HfApi()
    username = api.whoami(token=auth.token)["name"]
    bucket_id = f"{username}/research-agent"
    workspace = job.artifact_id
    manifest_path = f"{workspace}/{RESEARCH_MANIFEST}"

    with tempfile.TemporaryDirectory() as directory:
        local = Path(directory)
        manifest_local = local / "manifest.json"
        report_local = local / "report.md"
        api.download_bucket_files(
            bucket_id,
            [
                (manifest_path, manifest_local),
                (f"{workspace}/output/report.md", report_local),
            ],
            raise_on_missing_files=True,
            token=auth.token,
        )
        manifest = json.loads(manifest_local.read_text())
        report = report_local.read_text()

    artifacts = validate_stage_manifest(
        manifest,
        stage="research",
        allowed_prefixes=("scratch/research/", "output/"),
    )
    paths = {f"{workspace}/{path}" for path in artifacts}
    paths.add(f"{workspace}/output/report.md")
    available = {
        getattr(item, "path", ""): int(getattr(item, "size", 0) or 0)
        for item in api.list_bucket_tree(
            bucket_id,
            prefix=workspace,
            recursive=True,
            token=auth.token,
        )
        if getattr(item, "type", None) == "file"
    }
    missing = sorted(path for path in paths if available.get(path, 0) <= 0)
    if missing:
        raise FileNotFoundError(
            "Research handoff declared missing or empty artifacts: "
            + ", ".join(missing)
        )
    if "output/report.md" not in artifacts:
        raise ValueError("Research manifest must declare output/report.md")
    updated_report = embed_declared_figures(
        report,
        manifest,
        bucket_id=bucket_id,
        workspace=workspace,
    )
    if updated_report != report:
        api.batch_bucket_files(
            bucket_id,
            add=[
                (
                    updated_report.encode(),
                    f"{workspace}/output/report.md",
                )
            ],
            token=auth.token,
        )
    return manifest


def embed_declared_figures(
    report: str,
    manifest: dict[str, Any],
    *,
    bucket_id: str,
    workspace: str,
) -> str:
    """Append manifest-declared figures omitted from the Markdown report."""
    references = {
        path
        for match in MARKDOWN_IMAGE.finditer(report)
        if (
            path := _report_image_path(
                match.group("angle") or match.group("plain") or "",
                bucket_id=bucket_id,
                workspace=workspace,
            )
        )
    }
    figures = []
    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict) or record.get("role") != "figure":
            continue
        path = safe_artifact_path(record.get("path"))
        media_type = str(record.get("media_type", "")).lower()
        if PurePosixPath(path).suffix.lower() not in EMBEDDABLE_FIGURE_TYPES.get(
            media_type,
            set(),
        ):
            raise ValueError(
                "Report figures must be PNG, JPEG, or WebP to render safely: "
                f"{path}"
            )
        figures.append(path)
    missing = [path for path in figures if path not in references]
    if not missing:
        return report

    lines = [report.rstrip(), "", "## Figures", ""]
    for path in missing:
        alt = (
            re.sub(
            r"[^A-Za-z0-9 ._-]+",
            " ",
            PurePosixPath(path).stem,
            )
            .replace("-", " ")
            .replace("_", " ")
            .strip()
            .title()
            or "Report Figure"
        )
        encoded = "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)
        url = (
            f"https://huggingface.co/buckets/{bucket_id}/resolve/"
            f"{quote(workspace, safe='')}/{encoded}"
        )
        lines.extend((f"![{alt}]({url})", ""))
    return "\n".join(lines).rstrip() + "\n"


def _report_image_path(
    source: str,
    *,
    bucket_id: str,
    workspace: str,
) -> str | None:
    try:
        parsed = urlsplit(source)
    except ValueError:
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.scheme or parsed.netloc:
        prefix = f"/buckets/{bucket_id}/resolve/{workspace}/"
        main_prefix = f"/buckets/{bucket_id}/resolve/main/{workspace}/"
        if parsed.scheme != "https" or parsed.netloc != "huggingface.co":
            return None
        path = next(
            (
                parsed.path.removeprefix(candidate)
                for candidate in (prefix, main_prefix)
                if parsed.path.startswith(candidate)
            ),
            None,
        )
        if path is None:
            return None
    else:
        path = parsed.path
        if not path.startswith(("output/", "scratch/")):
            path = f"output/{path}"
    decoded = unquote(path)
    try:
        return safe_artifact_path(decoded)
    except ValueError:
        return None


def validate_stage_manifest(
    manifest: object,
    *,
    stage: str,
    allowed_prefixes: tuple[str, ...],
) -> tuple[str, ...]:
    """Validate a bounded stage manifest and return declared relative paths."""
    if not isinstance(manifest, dict):
        raise ValueError("Artifact manifest must be a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Artifact manifest schema_version must be {SCHEMA_VERSION}")
    if manifest.get("stage") != stage:
        raise ValueError(f"Artifact manifest stage must be {stage!r}")
    if manifest.get("status") != "complete":
        raise ValueError("Artifact manifest status must be 'complete'")

    records = manifest.get("artifacts")
    if not isinstance(records, list) or not records:
        raise ValueError("Artifact manifest must declare at least one artifact")
    if len(records) > MAX_MANIFEST_ARTIFACTS:
        raise ValueError(
            f"Artifact manifest exceeds {MAX_MANIFEST_ARTIFACTS} artifacts"
        )

    paths: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Artifact manifest entries must be JSON objects")
        path = safe_artifact_path(record.get("path"))
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in allowed_prefixes
        ):
            raise ValueError(f"Artifact path is outside the {stage} boundary: {path}")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise ValueError("Artifact manifest contains duplicate paths")
    return tuple(paths)


def safe_artifact_path(value: object) -> str:
    """Return one normalized workspace-relative artifact path."""
    raw = str(value or "").strip()
    candidate = PurePosixPath(raw)
    normalized = posixpath.normpath(raw)
    if (
        not raw
        or candidate.is_absolute()
        or ".." in candidate.parts
        or normalized in {"", "."}
        or normalized.startswith("../")
    ):
        raise ValueError(f"Artifact path must be workspace-relative: {raw!r}")
    return normalized
