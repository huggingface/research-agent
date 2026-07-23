"""Deterministic post-processing for bucket HTML artifacts."""

from __future__ import annotations

import base64
import json
import posixpath
import re
import tempfile
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi
from huggingface_hub.errors import RemoteEntryNotFoundError

from fast_agent import AgentAuth

from .artifact_contract import validate_stage_manifest
from .app_jobs import ResearchJob

MARKER = "__BIRCH_SYSTEM_CSS__"
STYLE_RE = re.compile(
    r"<style\b(?=[^>]*\bdata-birch-system\b)[^>]*>.*?</style>",
    re.I | re.S,
)
STYLE_CONTENT_RE = re.compile(
    r"<style\b(?=[^>]*\bdata-birch-system\b)[^>]*>(?P<css>.*?)</style>",
    re.I | re.S,
)
MARKER_STYLE_RE = re.compile(
    rf"<style\b[^>]*>\s*{re.escape(MARKER)}\s*</style>",
    re.I | re.S,
)
PAGE_RE = re.compile(
    r'<main\b[^>]*\bclass=["\'][^"\']*\bpage\b[^"\']*["\']',
    re.I,
)
MAIN_CLASS_RE = re.compile(r'(<main\b[^>]*\bclass=["\'])([^"\']*)', re.I)
MAIN_RE = re.compile(r"<main\b", re.I)
ASSET_REF_RE = re.compile(
    r"""(?:src|href)=["'](?P<value>[^"'#?]+)(?:[?#][^"']*)?["']""",
    re.I,
)
LOCAL_ASSET_SRC_RE = re.compile(
    r"""(?P<prefix>\bsrc\s*=\s*)(?P<quote>["'])(?P<value>assets/[^"'#?]+)(?P=quote)""",
    re.I,
)
MAX_PRESENTATION_BYTES = 25 * 1024 * 1024
SAFE_ASSET_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".csv": "text/csv",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def finalize_bucket_html(
    job: ResearchJob,
    auth: AgentAuth | None,
    home: Path,
    *,
    api: HfApi | None = None,
    required: bool = False,
) -> tuple[str, str] | None:
    """Finalize a Birch draft without requiring Hugging Face Jobs."""
    if auth is None or not auth.token:
        if required:
            raise RuntimeError("Caller authentication is required to publish HTML")
        return None

    api = api or HfApi()
    username = api.whoami(token=auth.token)["name"]
    bucket_id = f"{username}/research-agent"
    attempt = max(1, job.birch_finalize_attempts)
    attempt_root = f"scratch/presentation/attempts/{attempt}"
    attempt_path = f"{job.artifact_id}/{attempt_root}/report.html"
    legacy_draft_path = f"{job.artifact_id}/scratch/report.html"
    output_path = f"{job.artifact_id}/output/report.html"
    draft_paths = (
        (attempt_path, legacy_draft_path, output_path)
        if hasattr(api, "list_bucket_tree")
        else (legacy_draft_path, output_path)
    )

    with tempfile.TemporaryDirectory() as directory:
        local_root = Path(directory)
        local = local_root / "report.html"
        source_path = _download_first(
            api,
            bucket_id,
            draft_paths,
            local,
            auth.token,
        )
        if source_path is None:
            if required:
                raise FileNotFoundError(
                    f"Birch draft was not staged at {attempt_path}"
                )
            return None

        html = local.read_text()
        assets: list[tuple[bytes, str]] = []
        embedded_assets: dict[str, tuple[str, bytes]] = {}
        if source_path == attempt_path:
            assets, embedded_assets = _load_presentation_assets(
                api,
                bucket_id,
                job.artifact_id,
                attempt_root,
                html,
                local_root,
                auth.token,
            )
            html = _embed_presentation_assets(html, embedded_assets)
        css = _birch_css_path(home).read_text()
        if MARKER in html:
            finalized = _ensure_page_shell(_inject_birch_css(html, css))
        elif source_path == output_path:
            _validate_html(html)
            return _artifact_urls(username, job.artifact_id)
        elif _has_trusted_birch_css(html, css):
            finalized = _ensure_page_shell(html)
        else:
            if required:
                raise ValueError(
                    "Birch draft has neither a stylesheet placeholder nor the "
                    "exact trusted stylesheet"
                )
            return None
        _validate_html(finalized)
        api.batch_bucket_files(
            bucket_id,
            add=[(finalized.encode(), output_path), *assets],
            token=auth.token,
        )
        job.add_event(
            "Finalized Birch HTML with the bundled stylesheet",
            kind="artifact",
        )
        return _artifact_urls(username, job.artifact_id)


def _load_presentation_assets(
    api: Any,
    bucket_id: str,
    workspace: str,
    attempt_root: str,
    html: str,
    local_root: Path,
    token: str,
) -> tuple[list[tuple[bytes, str]], dict[str, tuple[str, bytes]]]:
    manifest_remote = f"{workspace}/{attempt_root}/manifest.json"
    manifest_local = local_root / "manifest.json"
    api.download_bucket_files(
        bucket_id,
        [(manifest_remote, manifest_local)],
        raise_on_missing_files=True,
        token=token,
    )
    manifest = json.loads(manifest_local.read_text())
    paths = validate_stage_manifest(
        manifest,
        stage="presentation",
        allowed_prefixes=(f"{attempt_root}/",),
    )
    report_path = f"{attempt_root}/report.html"
    if manifest.get("entrypoint") != report_path or report_path not in paths:
        raise ValueError("Presentation manifest must declare its report entrypoint")

    asset_prefix = f"{attempt_root}/assets/"
    asset_paths = tuple(path for path in paths if path.startswith(asset_prefix))
    declared_refs = {
        posixpath.relpath(path, attempt_root): path for path in asset_paths
    }
    referenced = _relative_asset_references(html)
    undeclared = sorted(referenced - declared_refs.keys())
    if undeclared:
        raise ValueError(
            "HTML references assets not declared by the presentation manifest: "
            + ", ".join(undeclared)
        )

    uploads: list[tuple[bytes, str]] = []
    embeds: dict[str, tuple[str, bytes]] = {}
    total = 0
    for index, path in enumerate(asset_paths):
        suffix = _path_suffix(path)
        media_type = SAFE_ASSET_MEDIA_TYPES.get(suffix)
        if media_type is None:
            raise ValueError(f"Unsupported presentation asset type: {path}")
        local = local_root / f"asset-{index}{suffix}"
        api.download_bucket_files(
            bucket_id,
            [(f"{workspace}/{path}", local)],
            raise_on_missing_files=True,
            token=token,
        )
        payload = local.read_bytes()
        total += len(payload)
        if not payload:
            raise ValueError(f"Presentation asset is empty: {path}")
        if total > MAX_PRESENTATION_BYTES:
            raise ValueError(
                f"Presentation assets exceed {MAX_PRESENTATION_BYTES} bytes"
            )
        relative = posixpath.relpath(path, asset_prefix)
        uploads.append((payload, f"{workspace}/output/assets/{relative}"))
        embeds[f"assets/{relative}"] = (media_type, payload)
    return uploads, embeds


def _path_suffix(path: str) -> str:
    """Return a normalized lowercase suffix for a POSIX artifact path."""
    return Path(path).suffix.lower()


def _relative_asset_references(html: str) -> set[str]:
    references: set[str] = set()
    for match in ASSET_REF_RE.finditer(html):
        value = match.group("value").strip()
        if (
            not value
            or value.startswith(("/", "http://", "https://", "hf://", "data:"))
        ):
            continue
        normalized = posixpath.normpath(value)
        if normalized.startswith("../"):
            raise ValueError(f"HTML asset reference escapes output/: {value}")
        if normalized.startswith("assets/"):
            references.add(normalized)
    return references


def _embed_presentation_assets(
    html: str,
    assets: dict[str, tuple[str, bytes]],
) -> str:
    """Embed declared local image sources while retaining published asset files."""

    def replace(match: re.Match[str]) -> str:
        value = posixpath.normpath(match.group("value"))
        asset = assets.get(value)
        if asset is None:
            return match.group(0)
        media_type, payload = asset
        if not media_type.startswith("image/"):
            return match.group(0)
        encoded = base64.b64encode(payload).decode("ascii")
        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"data:{media_type};base64,{encoded}{match.group('quote')}"
        )

    return LOCAL_ASSET_SRC_RE.sub(replace, html)


def read_bucket_markdown(
    job: ResearchJob,
    auth: AgentAuth | None,
    *,
    api: HfApi | None = None,
) -> str:
    """Read the completed Markdown report with the caller's token."""
    if auth is None or not auth.token:
        raise RuntimeError("Caller authentication is required to read the report")

    api = api or HfApi()
    username = api.whoami(token=auth.token)["name"]
    bucket_id = f"{username}/research-agent"
    report_path = f"{job.artifact_id}/output/report.md"

    with tempfile.TemporaryDirectory() as directory:
        local = Path(directory) / "report.md"
        api.download_bucket_files(
            bucket_id,
            [(report_path, local)],
            raise_on_missing_files=True,
            token=auth.token,
        )
        return local.read_text()


def _inject_birch_css(html: str, css: str) -> str:
    """Normalize a marker-only style element and inject trusted Birch CSS."""
    replacement = f"<style data-birch-system>{css.strip()}</style>"
    if MARKER_STYLE_RE.search(html):
        return MARKER_STYLE_RE.sub(replacement, html, count=1)
    return html.replace(MARKER, css.strip())


def _has_trusted_birch_css(html: str, css: str) -> bool:
    match = STYLE_CONTENT_RE.search(html)
    return match is not None and match.group("css").strip() == css.strip()


def _ensure_page_shell(html: str) -> str:
    """Add Birch's required `.page` class to the first main element."""
    if PAGE_RE.search(html):
        return html
    if MAIN_CLASS_RE.search(html):
        return MAIN_CLASS_RE.sub(r"\1page \2", html, count=1)
    if MAIN_RE.search(html):
        return MAIN_RE.sub('<main class="page"', html, count=1)
    return html


def _download_first(
    api: Any,
    bucket_id: str,
    remote_paths: tuple[str, ...],
    local_path: Path,
    token: str,
) -> str | None:
    for remote_path in remote_paths:
        try:
            api.download_bucket_files(
                bucket_id,
                [(remote_path, local_path)],
                raise_on_missing_files=True,
                token=token,
            )
            return remote_path
        except RemoteEntryNotFoundError:
            continue
    return None


def _birch_css_path(home: Path) -> Path:
    candidates = (
        home / "skills" / "birch-html" / "assets" / "birch-system.css",
        home.parent
        / "deploy"
        / "research-tool-one"
        / "skills"
        / "birch-html"
        / "assets"
        / "birch-system.css",
    )
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Bundled Birch stylesheet is missing")


def _validate_html(html: str) -> None:
    if MARKER in html:
        raise ValueError("Birch CSS placeholder remains")
    if not html.lstrip().lower().startswith("<!doctype html>"):
        raise ValueError("HTML artifact has no doctype")
    if not STYLE_RE.search(html):
        raise ValueError("HTML artifact has no embedded Birch stylesheet")
    if not PAGE_RE.search(html):
        raise ValueError("HTML artifact has no Birch page shell")
    if "</html>" not in html.lower():
        raise ValueError("HTML artifact is incomplete")


def _artifact_urls(username: str, job_id: str) -> tuple[str, str]:
    path = f"{job_id}/output/report.html"
    return (
        f"hf://buckets/{username}/research-agent/{path}",
        f"https://huggingface.co/buckets/{username}/research-agent/tree/{path}",
    )
