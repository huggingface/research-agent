"""Deterministic post-processing for bucket HTML artifacts."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi
from huggingface_hub.errors import RemoteEntryNotFoundError

from fast_agent import AgentAuth

from .app_jobs import ResearchJob

MARKER = "__BIRCH_SYSTEM_CSS__"
STYLE_RE = re.compile(
    r"<style\b(?=[^>]*\bdata-birch-system\b)[^>]*>.*?</style>",
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


def finalize_bucket_html(
    job: ResearchJob,
    auth: AgentAuth | None,
    home: Path,
    *,
    api: HfApi | None = None,
) -> tuple[str, str] | None:
    """Finalize a Birch draft without requiring Hugging Face Jobs."""
    if auth is None or not auth.token:
        return None

    api = api or HfApi()
    username = api.whoami(token=auth.token)["name"]
    bucket_id = f"{username}/research-agent"
    draft_path = f"{job.id}/scratch/report.html"
    output_path = f"{job.id}/output/report.html"

    with tempfile.TemporaryDirectory() as directory:
        local = Path(directory) / "report.html"
        source_path = _download_first(
            api,
            bucket_id,
            (draft_path, output_path),
            local,
            auth.token,
        )
        if source_path is None:
            return None

        html = local.read_text()
        if MARKER not in html:
            _validate_html(html)
            if source_path != output_path:
                return None
            return _artifact_urls(username, job.id)

        css = _birch_css_path(home).read_text()
        finalized = _ensure_page_shell(_inject_birch_css(html, css))
        _validate_html(finalized)
        api.batch_bucket_files(
            bucket_id,
            add=[(finalized.encode(), output_path)],
            token=auth.token,
        )
        job.add_event(
            "Finalized Birch HTML with the bundled stylesheet",
            kind="artifact",
        )
        return _artifact_urls(username, job.id)


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
    report_path = f"{job.id}/output/report.md"

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
