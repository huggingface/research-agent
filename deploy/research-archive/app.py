"""Research Dispatch archive over a mounted Hugging Face Bucket."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import bleach
import markdown
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

APP_ROOT = Path(__file__).parent
DEFAULT_RESEARCH_ROOT = Path(os.getenv("RESEARCH_ROOT", "/research"))
DEFAULT_READ_ONLY = os.getenv("RESEARCH_ARCHIVE_READ_ONLY", "").lower() in {
    "1",
    "true",
    "yes",
}
TEMPLATE_MARKER = json.loads((APP_ROOT / "archive-template.json").read_text())
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DATE_PREFIX = re.compile(r"^(?P<date>\d{2}-\d{2}-\d{2})-(?P<slug>.+?)-[a-f0-9]{4}$")
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
ARTIFACT_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "script-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'none'; "
    "connect-src 'none'; "
    "media-src 'none'; "
    "frame-src 'none'; "
    "worker-src 'none'; "
    "manifest-src 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'; "
    "sandbox allow-popups allow-popups-to-escape-sandbox"
)
ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "article",
    "blockquote",
    "br",
    "code",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "p",
    "pre",
    "span",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "td": ["align"],
    "th": ["align"],
}


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: str
    title: str
    date: str
    updated_at: str
    status: str
    has_markdown: bool
    has_html: bool
    asset_count: int
    trace_count: int

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "updated_at": self.updated_at,
            "status": self.status,
            "has_markdown": self.has_markdown,
            "has_html": self.has_html,
            "asset_count": self.asset_count,
            "trace_count": self.trace_count,
        }


class ResearchArchive:
    """Inspect one mounted research bucket without an external index."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_runs(self) -> list[RunSummary]:
        if not self.root.is_dir():
            return []
        runs = [
            self.summarize(path)
            for path in self.root.iterdir()
            if path.is_dir() and SAFE_SEGMENT.fullmatch(path.name)
        ]
        return sorted(runs, key=lambda run: run.updated_at, reverse=True)

    def summarize(self, run: Path) -> RunSummary:
        markdown_path = run / "output" / "report.md"
        html_path = run / "output" / "report.html"
        has_markdown = markdown_path.is_file()
        has_html = html_path.is_file()
        status = (
            "complete"
            if has_markdown and has_html
            else "markdown"
            if has_markdown
            else "incomplete"
        )
        files = [path for path in run.rglob("*") if path.is_file()]
        updated = self._workspace_timestamp(run, files)
        return RunSummary(
            id=run.name,
            title=self._title(run.name, markdown_path),
            date=self._date(run.name, updated),
            updated_at=datetime.fromtimestamp(updated, UTC).isoformat(),
            status=status,
            has_markdown=has_markdown,
            has_html=has_html,
            asset_count=sum("/assets/" in path.as_posix() for path in files),
            trace_count=sum("/traces/" in path.as_posix() for path in files),
        )

    def describe(self, run_id: str) -> dict[str, Any]:
        run = self.run_path(run_id)
        if not run.is_dir():
            raise FileNotFoundError(run_id)
        summary = self.summarize(run)
        markdown_path = run / "output" / "report.md"
        markdown_text = (
            markdown_path.read_text(errors="replace") if markdown_path.is_file() else ""
        )
        research_manifest = self._read_json(
            run / "scratch" / "research" / "manifest.json"
        )
        presentation_manifests = [
            self._read_json(path)
            for path in sorted(
                (run / "scratch" / "presentation" / "attempts").glob("*/manifest.json")
            )
        ]
        files = [
            {
                "path": path.relative_to(run).as_posix(),
                "size": path.stat().st_size,
                "kind": self._kind(path),
            }
            for path in sorted(run.rglob("*"))
            if path.is_file() and path.name not in {".keep", ".workspace.json"}
        ]
        return {
            **summary.json(),
            "markdown": markdown_text,
            "markdown_html": render_markdown(markdown_text),
            "research_manifest": research_manifest,
            "presentation_manifests": presentation_manifests,
            "files": files,
            "markdown_url": (
                f"/files/{run_id}/output/report.md" if summary.has_markdown else None
            ),
            "html_url": (
                f"/files/{run_id}/output/report.html" if summary.has_html else None
            ),
        }

    def run_path(self, run_id: str) -> Path:
        if not SAFE_SEGMENT.fullmatch(run_id):
            raise ValueError("Invalid run id")
        return self.root / run_id

    def file_path(self, run_id: str, relative: str) -> Path:
        run = self.run_path(run_id)
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Invalid artifact path")
        path = run.joinpath(*candidate.parts)
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    def delete(self, run_id: str) -> None:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        shutil.rmtree(run)

    @staticmethod
    def _read_json(path: Path) -> object | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _workspace_timestamp(cls, run: Path, files: list[Path]) -> float:
        marker = cls._read_json(run / "scratch" / ".workspace.json")
        if isinstance(marker, dict):
            checked_at = marker.get("checked_at")
            if isinstance(checked_at, str):
                try:
                    return datetime.fromisoformat(checked_at).timestamp()
                except ValueError:
                    pass
        return max(
            (path.stat().st_mtime for path in files),
            default=run.stat().st_mtime,
        )

    @staticmethod
    def _title(run_id: str, report: Path) -> str:
        if report.is_file():
            match = HEADING.search(report.read_text(errors="replace")[:8000])
            if match:
                return match.group(1).strip()
        match = DATE_PREFIX.match(run_id)
        slug = match.group("slug") if match else run_id.removeprefix("research-")
        return slug.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _date(run_id: str, timestamp: float) -> str:
        match = DATE_PREFIX.match(run_id)
        if match:
            try:
                return (
                    datetime.strptime(match.group("date"), "%y-%m-%d")
                    .replace(tzinfo=UTC)
                    .date()
                    .isoformat()
                )
            except ValueError:
                pass
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()

    @staticmethod
    def _kind(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"}:
            return "image"
        if suffix == ".html":
            return "html"
        if suffix in {".md", ".txt"}:
            return "text"
        if suffix in {".json", ".jsonl", ".csv"}:
            return "data"
        if suffix == ".py":
            return "code"
        return "file"


def render_markdown(source: str) -> str:
    if not source:
        return ""
    rendered = markdown.markdown(
        source,
        extensions=["extra", "sane_lists", "tables"],
        output_format="html",
    )
    return bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "hf", "mailto"},
        strip=True,
    )


def create_app(
    root: Path = DEFAULT_RESEARCH_ROOT,
    *,
    read_only: bool = DEFAULT_READ_ONLY,
) -> FastAPI:
    archive = ResearchArchive(root)
    app = FastAPI(title="Research Archive", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (APP_ROOT / "index.html").read_text()

    @app.get("/assets/huggingface-logo.svg")
    def huggingface_logo() -> FileResponse:
        return FileResponse(
            APP_ROOT / "huggingface-logo.svg",
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/runs")
    def runs() -> dict[str, object]:
        entries = archive.list_runs()
        return {
            "runs": [entry.json() for entry in entries],
            "count": len(entries),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @app.get("/api/config")
    def config() -> dict[str, bool]:
        return {"read_only": read_only}

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        try:
            return archive.describe(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict[str, str]:
        if read_only:
            raise HTTPException(status_code=403, detail="Archive is read-only")
        try:
            archive.delete(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not delete run") from exc
        return {"deleted": run_id}

    @app.get("/files/{run_id}/{relative:path}")
    def artifact(
        run_id: str,
        relative: str,
        download: bool = Query(default=False),
    ) -> FileResponse:
        try:
            path = archive.file_path(run_id, relative)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{path.name}"'
                    if download
                    else f'inline; filename="{path.name}"'
                ),
                "Cache-Control": "private, max-age=300",
                "Content-Security-Policy": ARTIFACT_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": root.is_dir(),
            "root": str(root),
            "read_only": read_only,
            "template_version": TEMPLATE_MARKER["template_version"],
        }

    return app


app = create_app()
