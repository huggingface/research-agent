"""Research Dispatch archive over a mounted Hugging Face Bucket."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import bleach
import markdown
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from latex2mathml.converter import convert as latex_to_mathml

APP_ROOT = Path(__file__).parent
DEFAULT_RESEARCH_ROOT = Path(os.getenv("RESEARCH_ROOT", "/research"))
DEFAULT_BUCKET_ID = os.getenv("RESEARCH_ARCHIVE_BUCKET")
DEFAULT_READ_ONLY = os.getenv("RESEARCH_ARCHIVE_READ_ONLY", "").lower() in {
    "1",
    "true",
    "yes",
}
TEMPLATE_MARKER = json.loads((APP_ROOT / "archive-template.json").read_text())
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DATE_PREFIX = re.compile(r"^(?P<date>\d{2}-\d{2}-\d{2})-(?P<slug>.+?)-[a-f0-9]{4}$")
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
IMAGE_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
DISPLAY_MATH = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL)
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
MATHML_TAGS = {
    "annotation",
    "math",
    "merror",
    "mfrac",
    "mi",
    "mmultiscripts",
    "mn",
    "mo",
    "mover",
    "mpadded",
    "mphantom",
    "mroot",
    "mrow",
    "mspace",
    "msqrt",
    "mstyle",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
    "semantics",
}
MATHML_ATTRIBUTES = {
    "accent",
    "accentunder",
    "columnalign",
    "columnspacing",
    "columnspan",
    "denomalign",
    "display",
    "encoding",
    "fence",
    "form",
    "linethickness",
    "lspace",
    "mathvariant",
    "notation",
    "numalign",
    "rowalign",
    "rowspan",
    "rspace",
    "separator",
    "stretchy",
    "symmetric",
    "width",
}
SAFE_IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".webp"}
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
    "img",
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
BASE_ALLOWED_ATTRIBUTES = {
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
    asset_count: int | None
    trace_count: int | None

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

    def __init__(self, root: Path, *, bucket_id: str | None = None) -> None:
        self.root = root
        self.bucket_id = bucket_id if bucket_id is not None else DEFAULT_BUCKET_ID

    def list_runs(self) -> list[RunSummary]:
        if not self.root.is_dir():
            return []
        runs = [
            self.summarize(path)
            for path in self.root.iterdir()
            if (
                path.is_dir()
                and not path.is_symlink()
                and SAFE_SEGMENT.fullmatch(path.name)
            )
        ]
        return sorted(runs, key=lambda run: run.updated_at, reverse=True)

    def summarize(self, run: Path) -> RunSummary:
        markdown_path = self._direct_file(run, run / "output" / "report.md")
        html_path = self._direct_file(run, run / "output" / "report.html")
        has_markdown = markdown_path is not None
        has_html = html_path is not None
        status = (
            "complete"
            if has_markdown and has_html
            else "markdown"
            if has_markdown
            else "incomplete"
        )
        updated = self._workspace_timestamp(run, markdown_path, html_path)
        return RunSummary(
            id=run.name,
            title=self._title(run.name, markdown_path),
            date=self._date(run.name, updated),
            updated_at=datetime.fromtimestamp(updated, UTC).isoformat(),
            status=status,
            has_markdown=has_markdown,
            has_html=has_html,
            asset_count=None,
            trace_count=None,
        )

    def describe(self, run_id: str) -> dict[str, Any]:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        summary = self.summarize(run)
        markdown_detail = (
            self.markdown(run_id)
            if summary.has_markdown
            else {"markdown": "", "markdown_html": ""}
        )
        research_manifest = self._read_json(
            run,
            run / "scratch" / "research" / "manifest.json",
        )
        presentation_manifests = [
            self._read_json(run, path)
            for path in sorted(
                (run / "scratch" / "presentation" / "attempts").glob("*/manifest.json")
            )
        ]
        return {
            **summary.json(),
            **markdown_detail,
            "research_manifest": research_manifest,
            "presentation_manifests": presentation_manifests,
            "markdown_url": (
                f"/files/{run_id}/output/report.md" if summary.has_markdown else None
            ),
            "html_url": (
                f"/files/{run_id}/output/report.html" if summary.has_html else None
            ),
        }

    def markdown(self, run_id: str) -> dict[str, str]:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        path = self._direct_file(run, run / "output" / "report.md")
        if path is None:
            raise FileNotFoundError("output/report.md")
        text = path.read_text(errors="replace")
        return {
            "markdown": text,
            "markdown_html": render_markdown(text, run_id=run_id, archive=self),
        }

    def files(self, run_id: str) -> list[dict[str, str | int]]:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        resolved_run = run.resolve()
        files: list[dict[str, str | int]] = []
        for path in sorted(run.rglob("*")):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.name in {".keep", ".workspace.json"}
            ):
                continue
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(resolved_run):
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            files.append(
                {
                    "path": path.relative_to(run).as_posix(),
                    "size": size,
                    "kind": self._kind(path),
                }
            )
        return files

    def run_path(self, run_id: str) -> Path:
        if not SAFE_SEGMENT.fullmatch(run_id):
            raise ValueError("Invalid run id")
        return self.root / run_id

    def file_path(self, run_id: str, relative: str) -> Path:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Invalid artifact path")
        path = run.joinpath(*candidate.parts)
        resolved_root = self.root.resolve()
        resolved_run = run.resolve()
        resolved_path = path.resolve()
        if (
            not resolved_run.is_relative_to(resolved_root)
            or not resolved_path.is_relative_to(resolved_run)
            or not resolved_path.is_file()
        ):
            raise FileNotFoundError(relative)
        return resolved_path

    def delete(self, run_id: str) -> None:
        run = self.run_path(run_id)
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(run_id)
        shutil.rmtree(run)

    @classmethod
    def _direct_file(cls, run: Path, path: Path) -> Path | None:
        try:
            relative = path.relative_to(run)
            current = run
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    return None
            resolved_run = run.resolve()
            resolved = path.resolve(strict=True)
        except (OSError, ValueError):
            return None
        if not resolved.is_relative_to(resolved_run) or not resolved.is_file():
            return None
        return resolved

    @classmethod
    def _read_json(cls, run: Path, path: Path) -> object | None:
        path = cls._direct_file(run, path)
        if path is None:
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _workspace_timestamp(
        cls,
        run: Path,
        markdown_path: Path | None,
        html_path: Path | None,
    ) -> float:
        marker = cls._read_json(run, run / "scratch" / ".workspace.json")
        if isinstance(marker, dict):
            checked_at = marker.get("checked_at")
            if isinstance(checked_at, str):
                try:
                    return datetime.fromisoformat(checked_at).timestamp()
                except ValueError:
                    pass
        # Legacy runs without markers are ordered by direct report metadata.
        candidates = [run, *(path for path in (markdown_path, html_path) if path)]
        return max(path.stat().st_mtime for path in candidates)

    @staticmethod
    def _title(run_id: str, report: Path | None) -> str:
        if report:
            with report.open(errors="replace") as handle:
                match = HEADING.search(handle.read(8000))
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


def render_markdown(
    source: str,
    *,
    run_id: str | None = None,
    archive: ResearchArchive | None = None,
) -> str:
    if not source:
        return ""
    source, math = _extract_display_math(source)
    rendered = markdown.markdown(
        source,
        extensions=["extra", "sane_lists", "tables"],
        output_format="html",
    )
    if run_id is not None and archive is not None:
        rendered = _rewrite_rendered_images(rendered, run_id, archive)
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=_allowed_attribute(run_id),
        protocols={"http", "https", "hf", "mailto"},
        strip=True,
    )
    cleaned = re.sub(
        r"<img(?P<attributes>[^>]*)>",
        lambda match: (
            match.group(0) if re.search(r"\bsrc\s*=", match.group("attributes")) else ""
        ),
        cleaned,
    )
    for placeholder, mathml in math.items():
        cleaned = cleaned.replace(placeholder, mathml)
    return cleaned


def _extract_display_math(source: str) -> tuple[str, dict[str, str]]:
    math: dict[str, str] = {}
    nonce = secrets.token_hex(8)

    def replace(match: re.Match[str]) -> str:
        placeholder = f"LATEXMATH{nonce}{len(math)}BLOCK"
        tex = match.group(1).strip()
        try:
            math[placeholder] = _sanitize_mathml(
                latex_to_mathml(tex, display="block")
            )
        except Exception:
            math[placeholder] = (
                f"<pre><code>{escape(f'$$\\n{tex}\\n$$')}</code></pre>"
            )
        return placeholder

    return DISPLAY_MATH.sub(replace, source), math


def _sanitize_mathml(value: str) -> str:
    root = ET.fromstring(value)
    if root.tag.rsplit("}", 1)[-1] != "math":
        raise ValueError("MathML root must be <math>")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in MATHML_TAGS:
            raise ValueError(f"Unsupported MathML element: {tag}")
        element.attrib = {
            key.rsplit("}", 1)[-1]: attribute[:100]
            for key, attribute in element.attrib.items()
            if key.rsplit("}", 1)[-1] in MATHML_ATTRIBUTES
        }
    ET.register_namespace("", MATHML_NAMESPACE)
    return ET.tostring(root, encoding="unicode")


def _rewrite_rendered_images(
    rendered: str,
    run_id: str,
    archive: ResearchArchive,
) -> str:
    def replace(match: re.Match[str]) -> str:
        attributes = _image_attributes(match.group(0))
        alt = attributes.get("alt", "").strip() or "Report image"
        relative = _archive_image_path(
            attributes.get("src", ""),
            run_id,
            archive.bucket_id,
        )
        if relative is None:
            return f"<span>Image unavailable: {escape(alt)}</span>"
        try:
            archive.file_path(run_id, relative)
        except (FileNotFoundError, ValueError):
            return f"<span>Image unavailable: {escape(alt)}</span>"
        route = "/files/" + "/".join(
            quote(part, safe="") for part in (run_id, *PurePosixPath(relative).parts)
        )
        title = attributes.get("title")
        title_attribute = f' title="{escape(title, quote=True)}"' if title else ""
        return f'<img alt="{escape(alt, quote=True)}" src="{route}"{title_attribute}>'

    return IMAGE_TAG.sub(replace, rendered)


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attributes: dict[str, str] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "img":
            self.attributes = {
                name: value or ""
                for name, value in attrs
                if name in {"alt", "src", "title"}
            }


def _image_attributes(tag: str) -> dict[str, str]:
    parser = _ImageParser()
    parser.feed(tag)
    return parser.attributes


def _archive_image_path(
    source: str,
    run_id: str,
    bucket_id: str | None,
) -> str | None:
    if not source or "\\" in source or "\x00" in source:
        return None
    try:
        parsed = urlsplit(source)
    except ValueError:
        return None
    if parsed.query or parsed.fragment:
        return None

    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme != "https"
            or parsed.netloc != "huggingface.co"
            or not bucket_id
        ):
            return None
        prefixes = (
            f"/buckets/{bucket_id}/resolve/{run_id}/",
            f"/buckets/{bucket_id}/resolve/main/{run_id}/",
            f"/buckets/{bucket_id}/tree/{run_id}/",
        )
        prefix = next(
            (candidate for candidate in prefixes if parsed.path.startswith(candidate)),
            None,
        )
        if prefix is None:
            return None
        path = parsed.path.removeprefix(prefix)
    else:
        path = parsed.path
        if not path.startswith(("output/", "scratch/")):
            path = f"output/{path}"

    decoded = unquote(path)
    if decoded.startswith("/") or decoded != path:
        return None
    parts = PurePosixPath(decoded).parts
    if (
        not parts
        or parts[0] not in {"output", "scratch"}
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(decoded).suffix.lower() not in SAFE_IMAGE_SUFFIXES
    ):
        return None
    return PurePosixPath(*parts).as_posix()


def _allowed_attribute(run_id: str | None):
    image_prefix = f"/files/{quote(run_id, safe='')}/" if run_id else None

    def allow(tag: str, name: str, value: str) -> bool:
        if tag == "img":
            if name == "src":
                return image_prefix is not None and value.startswith(image_prefix)
            return name in {"alt", "title"}
        return name in BASE_ALLOWED_ATTRIBUTES.get(tag, ())

    return allow


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

    @app.get("/api/runs/{run_id}/files")
    def run_files(run_id: str) -> dict[str, object]:
        try:
            files = archive.files(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"files": files, "count": len(files)}

    @app.get("/api/runs/{run_id}/markdown")
    def run_markdown(run_id: str) -> dict[str, str]:
        try:
            return archive.markdown(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Markdown not found") from exc

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
