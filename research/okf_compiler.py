"""Deterministic OKF v0.2 projection of a verified research report."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml
from fast_agent import AgentAuth
from huggingface_hub import HfApi

from .app_jobs import ResearchJob

OKF_VERSION = "0.2"
COMPILER_ACTOR = "research-agent/okf-compiler-v1"
EVIDENCE_PATH = "scratch/research/evidence.json"
KNOWLEDGE_MANIFEST = "scratch/knowledge/manifest.json"
MAX_REPORT_BYTES = 2_000_000
MAX_EVIDENCE_BYTES = 500_000
MAX_SOURCES = 256
SOURCE_ID = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
BARE_URL = re.compile(r"https?://[^\s<>\]\"'`]+")
FOOTNOTE_REF = re.compile(r"\[\^([A-Za-z][A-Za-z0-9._-]{1,63})\]")
FOOTNOTE_DEF = re.compile(
    r"^\s{0,3}\[\^([A-Za-z][A-Za-z0-9._-]{1,63})\]:",
    re.MULTILINE,
)
FOOTNOTE_LINK = re.compile(
    r"^\s{0,3}\[\^([A-Za-z][A-Za-z0-9._-]{1,63})\]:\s*"
    r"(?:\[([^\]\n]+)\]\((https?://[^)\s]+)\)|(https?://\S+))",
    re.MULTILINE,
)
HTML_OPEN = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?>")
HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "code",
    "credential",
    "key",
    "secret",
    "signature",
    "sig",
    "token",
}
SUMMARY_HEADINGS = (
    "tl;dr",
    "tldr",
    "executive summary",
    "summary",
    "abstract",
)


@dataclass(frozen=True, slots=True)
class OkfBuild:
    bundle_uri: str
    bundle_url: str
    bundle_sha256: str
    report_sha256: str
    source_count: int
    citation_count: int
    warnings: tuple[str, ...]


def compile_okf_bundle(
    job: ResearchJob,
    auth: AgentAuth,
    *,
    api: HfApi | None = None,
    clock: Callable[[], datetime] | None = None,
) -> OkfBuild:
    """Compile and publish a private OKF bundle; write its manifest last."""
    if not auth.token:
        raise RuntimeError("Caller authentication is required to publish OKF")
    api = api or HfApi()
    username = api.whoami(token=auth.token)["name"]
    bucket_id = f"{username}/research-agent"
    workspace = job.artifact_id
    report_path = f"{workspace}/output/report.md"
    evidence_path = f"{workspace}/{EVIDENCE_PATH}"
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
    report_size = available.get(report_path, 0)
    if report_size <= 0:
        raise FileNotFoundError("Verified Markdown report is unavailable")
    if report_size > MAX_REPORT_BYTES:
        raise ValueError("Markdown report exceeds the OKF compiler size limit")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        report_local = root / "report.md"
        downloads: list[tuple[str, Path]] = [(report_path, report_local)]
        evidence_local = root / "evidence.json"
        evidence_size = available.get(evidence_path, 0)
        if evidence_size > MAX_EVIDENCE_BYTES:
            raise ValueError("Structured evidence exceeds the OKF compiler size limit")
        if evidence_size > 0:
            downloads.append((evidence_path, evidence_local))
        api.download_bucket_files(
            bucket_id,
            downloads,
            raise_on_missing_files=True,
            token=auth.token,
        )
        report_bytes = report_local.read_bytes()
        report = report_bytes.decode("utf-8")
        evidence_bytes = evidence_local.read_bytes() if evidence_local.exists() else None

    generated_at = (clock or (lambda: datetime.now(UTC)))().astimezone(UTC)
    files, metadata = build_okf_files(
        report,
        title=job.headline,
        description=job.topic,
        workspace_id=workspace,
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        evidence_bytes=evidence_bytes,
        generated_at=generated_at,
    )
    archive = _zip_bundle(files, generated_at)
    bundle_sha256 = hashlib.sha256(archive).hexdigest()
    additions = [
        (content, f"{workspace}/output/okf/{path}")
        for path, content in sorted(files.items())
    ]
    additions.append((archive, f"{workspace}/output/okf.zip"))
    api.batch_bucket_files(bucket_id, add=additions, token=auth.token)

    manifest = {
        "schema_version": 1,
        "stage": "knowledge",
        "status": "complete",
        "okf_version": OKF_VERSION,
        "generated": {
            "by": COMPILER_ACTOR,
            "at": _timestamp(generated_at),
        },
        "source_report_sha256": metadata["report_sha256"],
        "bundle_sha256": bundle_sha256,
        "source_count": metadata["source_count"],
        "citation_count": metadata["citation_count"],
        "warnings": metadata["warnings"],
        "artifacts": [
            {
                "path": f"output/okf/{path}",
                "media_type": "text/markdown",
                "role": "index" if path.endswith("index.md") else "knowledge",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(files.items())
        ]
        + [
            {
                "path": "output/okf.zip",
                "media_type": "application/zip",
                "role": "bundle",
                "sha256": bundle_sha256,
            }
        ],
    }
    api.batch_bucket_files(
        bucket_id,
        add=[
            (
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
                f"{workspace}/{KNOWLEDGE_MANIFEST}",
            )
        ],
        token=auth.token,
    )
    encoded_workspace = quote(workspace, safe="")
    return OkfBuild(
        bundle_uri=f"hf://buckets/{bucket_id}/{workspace}/output/okf.zip",
        bundle_url=(
            f"https://huggingface.co/buckets/{bucket_id}/resolve/"
            f"{encoded_workspace}/output/okf.zip?download=true"
        ),
        bundle_sha256=bundle_sha256,
        report_sha256=str(metadata["report_sha256"]),
        source_count=int(metadata["source_count"]),
        citation_count=int(metadata["citation_count"]),
        warnings=tuple(str(item) for item in metadata["warnings"]),
    )


def build_okf_files(
    report: str,
    *,
    title: str,
    description: str,
    workspace_id: str,
    report_sha256: str,
    evidence_bytes: bytes | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Build a conformant, bounded OKF bundle entirely in memory."""
    report_bytes = report.encode()
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise ValueError("Markdown report exceeds the OKF compiler size limit")
    generated_at = (generated_at or datetime.now(UTC)).astimezone(UTC)
    warnings: list[str] = []
    declared = _load_evidence(evidence_bytes, warnings)
    sources = _merge_sources(report, declared, warnings)
    transformed = report.rstrip() + "\n"
    cited = _citation_ids(report)
    source_ids = {source["id"] for source in sources}
    dangling = sorted(cited - source_ids)
    if dangling:
        warnings.append(
            "Report contains unresolved evidence footnotes: " + ", ".join(dangling)
        )
    uncited = sorted(source_ids - cited)
    if uncited:
        warnings.append("Evidence sources not cited in report: " + ", ".join(uncited))

    report_title = _report_title(report) or title.strip() or "Research Brief"
    report_description = _report_description(report, description)
    frontmatter: dict[str, Any] = {
        "type": "Research Report",
        "title": report_title,
        "description": report_description,
        "tags": ["research"],
        "status": "draft",
        "generated": {
            "by": COMPILER_ACTOR,
            "at": _timestamp(generated_at),
        },
        "sources": sources,
        "x_research_agent": {
            "workspace_id": workspace_id,
            "source_report_sha256": report_sha256,
        },
    }
    brief = _document(frontmatter, transformed)
    evidence_frontmatter: dict[str, Any] = {
        "type": "Evidence Register",
        "title": f"Evidence for {report_title}",
        "description": "Source records captured from the canonical research report.",
        "tags": ["research", "evidence"],
        "status": "draft",
        "generated": {
            "by": COMPILER_ACTOR,
            "at": _timestamp(generated_at),
        },
        "sources": sources,
        "x_research_agent": {
            "workspace_id": workspace_id,
            "source_report_sha256": report_sha256,
        },
    }
    evidence_body = _evidence_body(sources, cited)
    files = {
        "index.md": _root_index(),
        "reports/index.md": (
            "# Research Report\n\n"
            f"* [Brief](brief.md) - {_truncate(report_description, 180)}\n"
        ).encode(),
        "reports/brief.md": brief,
        "references/index.md": (
            b"# Evidence\n\n"
            b"* [Evidence register](evidence.md) - Sources captured from the report.\n"
        ),
        "references/evidence.md": _document(evidence_frontmatter, evidence_body),
    }
    for path, content in files.items():
        _validate_document(path, content)
    return files, {
        "report_sha256": report_sha256,
        "source_count": len(sources),
        "citation_count": len(cited & source_ids),
        "warnings": warnings,
    }


def _load_evidence(
    content: bytes | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not content:
        return []
    if len(content) > MAX_EVIDENCE_BYTES:
        warnings.append("Structured evidence was too large and was ignored.")
        return []
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        warnings.append("Structured evidence was invalid JSON and was ignored.")
        return []
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        warnings.append("Structured evidence used an unsupported schema and was ignored.")
        return []
    records = value.get("sources")
    if not isinstance(records, list):
        warnings.append("Structured evidence had no source list and was ignored.")
        return []
    if len(records) > MAX_SOURCES:
        warnings.append("Structured evidence exceeded the source limit and was truncated.")
    result: list[dict[str, Any]] = []
    for raw in records[:MAX_SOURCES]:
        if not isinstance(raw, dict):
            warnings.append("A non-object evidence source was ignored.")
            continue
        resource = _canonical_url(raw.get("resource"))
        if resource is None:
            warnings.append("An evidence source with an unsafe resource was ignored.")
            continue
        source: dict[str, Any] = {
            "id": _safe_source_id(raw.get("id"), resource),
            "resource": resource,
            "title": _one_line(raw.get("title") or resource, 180),
        }
        author = _one_line(raw.get("author"), 100)
        if author:
            source["author"] = author
        last_modified = str(raw.get("last_modified") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_modified):
            source["last_modified"] = last_modified
        result.append(source)
    return result


def _merge_sources(
    report: str,
    declared: list[dict[str, Any]],
    warnings: list[str],
) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    ids: dict[str, str] = {}
    for source in [*declared, *_footnote_sources(report)]:
        resource = source["resource"]
        source_id = source["id"]
        if source_id in ids and ids[source_id] != resource:
            warnings.append(
                f"Evidence ID {source_id!r} named multiple resources; "
                "a deterministic ID was used."
            )
            source = {**source, "id": _source_id(resource)}
        ids[source["id"]] = resource
        by_url.setdefault(resource, source)
    for label, resource in _external_links(report):
        by_url.setdefault(
            resource,
            {
                "id": _source_id(resource),
                "resource": resource,
                "title": _one_line(label or resource, 180),
            },
        )
    sources = sorted(by_url.values(), key=lambda item: (item["id"], item["resource"]))
    if len(sources) > MAX_SOURCES:
        warnings.append("Report sources exceeded the source limit and were truncated.")
        sources = sources[:MAX_SOURCES]
    return sources


def _external_links(report: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    fenced = False
    fence_marker = ""
    for line in report.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if not fenced:
                fenced = True
                fence_marker = marker
            elif marker == fence_marker:
                fenced = False
            continue
        if fenced or line.startswith(("    ", "\t")) or FOOTNOTE_DEF.match(line):
            continue
        visible = _without_inline_code(line)
        for match in LINK.finditer(visible):
            if resource := _canonical_url(match.group(2)):
                found.append((match.group(1), resource))
        for match in AUTOLINK.finditer(visible):
            if resource := _canonical_url(match.group(1)):
                found.append((resource, resource))
        bare_text = LINK.sub("", AUTOLINK.sub("", visible))
        for resource in _bare_urls(bare_text):
            found.append((resource, resource))
    return found


def _footnote_sources(report: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for match in FOOTNOTE_LINK.finditer(report):
        resource = _canonical_url(match.group(3) or match.group(4))
        if resource is None:
            continue
        result.append(
            {
                "id": _safe_source_id(match.group(1), resource),
                "resource": resource,
                "title": _one_line(match.group(2) or resource, 180),
            }
        )
    return result


def _citation_ids(report: str) -> set[str]:
    result: set[str] = set()
    fenced = False
    fence_marker = ""
    in_comment = False
    html_block = ""
    for line in report.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if not fenced:
                fenced = True
                fence_marker = marker
            elif marker == fence_marker:
                fenced = False
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if html_block:
            if re.search(rf"</{re.escape(html_block)}\s*>", line, re.IGNORECASE):
                html_block = ""
            continue
        if fenced or line.startswith(("    ", "\t")) or FOOTNOTE_DEF.match(line):
            continue
        visible = _without_inline_code(line)
        if "<!--" in visible:
            before, after = visible.split("<!--", 1)
            visible = before
            in_comment = "-->" not in after
        stripped = visible.strip()
        opening = HTML_OPEN.search(visible)
        if opening:
            tag = opening.group(1).lower()
            after = visible[opening.end() :]
            if (
                tag not in HTML_VOID_TAGS
                and not opening.group(0).endswith("/>")
                and not re.search(rf"</{re.escape(tag)}\s*>", after, re.IGNORECASE)
            ):
                html_block = tag
        if (
            not stripped
            or stripped.startswith("#")
            or "|" in stripped
            or HTML_TAG.search(visible)
        ):
            continue
        result.update(FOOTNOTE_REF.findall(visible))
    return result


def _bare_urls(value: str) -> list[str]:
    result: list[str] = []
    for match in BARE_URL.finditer(value):
        candidate = match.group(0).rstrip(".,;:!?)]}")
        if resource := _canonical_url(candidate):
            result.append(resource)
    return result


def _canonical_url(value: object) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    pairs = [
        part.split("=", 1)[0].lower()
        for part in re.split(r"[&;]", _fully_unquote(parsed.query))
        if part
    ]
    if any(key in SENSITIVE_QUERY_KEYS for key in pairs):
        return None
    host = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    netloc = host
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, "")
    )


def _fully_unquote(value: str) -> str:
    while True:
        decoded = unquote(value)
        if decoded == value:
            return value
        value = decoded


def _safe_source_id(value: object, resource: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if SOURCE_ID.fullmatch(candidate) else _source_id(resource)


def _source_id(resource: str) -> str:
    return f"src-{hashlib.sha256(resource.encode()).hexdigest()[:16]}"


def _report_title(report: str) -> str:
    match = HEADING.search(report[:20_000])
    return _one_line(match.group(1), 180) if match else ""


def _report_description(report: str, fallback: str) -> str:
    lines = report.splitlines()
    headings: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if not match:
            continue
        name = re.sub(r"[*_`]", "", match.group(1)).strip().lower()
        headings.setdefault(name, index)
    for heading in SUMMARY_HEADINGS:
        if heading not in headings:
            continue
        paragraph: list[str] = []
        for line in lines[headings[heading] + 1 :]:
            if re.match(r"^#{1,6}\s+", line):
                break
            stripped = line.strip()
            if not stripped:
                if paragraph:
                    break
                continue
            if stripped.startswith(("|", "```", "~~~", "![", "---")):
                if paragraph:
                    break
                continue
            paragraph.append(stripped)
        if paragraph:
            description = _plain_markdown(" ".join(paragraph))
            if description:
                return _truncate(description, 280)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith(("#", "|", "```", "~~~", "![", "---", "[^"))
        ):
            continue
        paragraph = [stripped]
        for continuation in lines[index + 1 :]:
            continuation = continuation.strip()
            if not continuation or continuation.startswith("#"):
                break
            paragraph.append(continuation)
        description = _plain_markdown(" ".join(paragraph))
        if description:
            return _truncate(description, 280)
    return _truncate(_one_line(fallback, 1000), 280)


def _plain_markdown(value: str) -> str:
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = FOOTNOTE_REF.sub("", value)
    value = re.sub(r"</?[^>]+>", "", value)
    value = re.sub(r"^[>*+\-\d.)\s]+", "", value)
    value = value.replace("`", "").replace("*", "").replace("_", "")
    return _one_line(value, 1000)


def _truncate(value: str, limit: int) -> str:
    value = _one_line(value, max(limit * 4, limit))
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened or value[: limit - 1]}…"


def _one_line(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _without_inline_code(line: str) -> str:
    parts = line.split("`")
    return "".join(part if index % 2 == 0 else " " * len(part) for index, part in enumerate(parts))


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _document(frontmatter: dict[str, Any], body: str) -> bytes:
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n".encode()


def _root_index() -> bytes:
    return (
        "---\n"
        f'okf_version: "{OKF_VERSION}"\n'
        "---\n\n"
        "# Research Knowledge\n\n"
        "* [Reports](reports/index.md) - Draft research report concepts.\n"
        "* [Evidence](references/index.md) - Sources captured from the report.\n"
    ).encode()


def _evidence_body(
    sources: list[dict[str, Any]],
    cited: set[str],
) -> str:
    lines = ["# Sources", ""]
    if not sources:
        return "# Sources\n\nNo machine-detectable external sources were found.\n"
    for source in sources:
        state = "cited" if source["id"] in cited else "not cited"
        lines.append(
            f"* **`{source['id']}`** — "
            f"[{source['title']}]({source['resource']}) ({state})"
        )
    return "\n".join(lines) + "\n"


def _validate_document(path: str, content: bytes) -> None:
    text = content.decode("utf-8")
    if path.endswith("index.md"):
        if path != "index.md" and text.startswith("---"):
            raise ValueError(f"Non-root OKF index has frontmatter: {path}")
        return
    if not text.startswith("---\n"):
        raise ValueError(f"OKF concept has no frontmatter: {path}")
    try:
        _, yaml_text, _ = text.split("---", 2)
        frontmatter = yaml.safe_load(yaml_text)
    except (ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"OKF concept has invalid frontmatter: {path}") from exc
    if not isinstance(frontmatter, dict) or not frontmatter.get("type"):
        raise ValueError(f"OKF concept has no type: {path}")
    sources = frontmatter.get("sources") or []
    ids = [source.get("id") for source in sources if isinstance(source, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError(f"OKF concept has duplicate source IDs: {path}")


def _zip_bundle(files: dict[str, bytes], generated_at: datetime) -> bytes:
    output = io.BytesIO()
    stamp = generated_at.astimezone(UTC)
    date_time = (
        max(1980, stamp.year),
        stamp.month,
        stamp.day,
        stamp.hour,
        stamp.minute,
        stamp.second,
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return output.getvalue()
