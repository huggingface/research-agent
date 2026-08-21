"""Bounded OKF v0.2 consumer for the private report archive."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml

MAX_DOCUMENT_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 500_000
MAX_BUNDLE_BYTES = 20_000_000
MAX_SOURCES = 256
MAX_ARCHIVE_MEMBERS = 64
SOURCE_ID = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
FOOTNOTE_REF = re.compile(r"\[\^([A-Za-z][A-Za-z0-9._-]{1,63})\]")
FOOTNOTE_DEF = re.compile(r"^\s{0,3}\[\^([A-Za-z][A-Za-z0-9._-]{1,63})\]:")
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\((https?://[^)\s]+)\)")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
BARE_URL = re.compile(r"https?://[^\s<>\]\"'`]+")
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


class OkfArchiveError(ValueError):
    pass


def inspect_okf(
    *,
    index: bytes,
    brief: bytes,
    manifest: bytes,
    bundle: bytes,
    report: str,
    expanded: dict[str, bytes] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a safe evidence projection; never execute or fetch bundle content."""
    expanded = expanded or {}
    if (
        len(index) > MAX_DOCUMENT_BYTES
        or len(brief) > MAX_DOCUMENT_BYTES
        or any(len(content) > MAX_DOCUMENT_BYTES for content in expanded.values())
    ):
        raise OkfArchiveError("OKF document exceeds the archive size limit")
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise OkfArchiveError("Knowledge manifest exceeds the archive size limit")
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise OkfArchiveError("OKF bundle exceeds the archive size limit")

    root_frontmatter, _ = _parse_frontmatter(index, root_index=True)
    version = str(root_frontmatter.get("okf_version") or "")
    if version != "0.2":
        raise OkfArchiveError(f"Unsupported OKF version: {version or 'missing'}")
    frontmatter, _body = _parse_frontmatter(brief)
    concept_type = str(frontmatter.get("type") or "").strip()
    if not concept_type:
        raise OkfArchiveError("OKF report concept has no type")
    try:
        release = _strict_json(manifest)
    except Exception as exc:
        raise OkfArchiveError("Knowledge manifest is invalid") from exc
    if (
        not isinstance(release, dict)
        or release.get("schema_version") != 1
        or release.get("stage") != "knowledge"
        or release.get("status") != "complete"
        or str(release.get("okf_version")) != version
    ):
        raise OkfArchiveError("Knowledge manifest contract is invalid")

    diagnostics: list[dict[str, str]] = []
    artifact_values = release.get("artifacts")
    artifact_values = artifact_values if isinstance(artifact_values, list) else []
    artifact_digests = {
        str(item.get("path")): str(item.get("sha256") or "")
        for item in artifact_values
        if isinstance(item, dict)
    }
    if len(artifact_digests) != len(artifact_values):
        diagnostics.append(
            _diagnostic(
                "error",
                "artifact-manifest",
                "The completion manifest has duplicate or invalid artifact records.",
            )
        )
    artifact_integrity = True
    loose_files = {
        "index.md": index,
        "reports/brief.md": brief,
        **expanded,
    }
    for member, content in loose_files.items():
        path = f"output/okf/{member}"
        if artifact_digests.get(path) != hashlib.sha256(content).hexdigest():
            artifact_integrity = False
            diagnostics.append(
                _diagnostic(
                    "error",
                    "artifact-integrity",
                    f"{path} does not match its completion manifest.",
                )
            )
    expected_digest = str(release.get("bundle_sha256") or "")
    actual_digest = hashlib.sha256(bundle).hexdigest()
    bundle_integrity = bool(
        re.fullmatch(r"[a-f0-9]{64}", expected_digest)
        and expected_digest == actual_digest
    )
    if not bundle_integrity:
        diagnostics.append(
            _diagnostic(
                "error",
                "bundle-integrity",
                "The downloadable bundle does not match its completion manifest.",
            )
        )
    archive_integrity = _validate_archive(
        bundle,
        artifact_digests,
        loose_files,
        diagnostics,
    )
    current_report_digest = hashlib.sha256(report.encode()).hexdigest()
    report_integrity = (
        str(release.get("source_report_sha256") or "") == current_report_digest
    )
    if not report_integrity:
        diagnostics.append(
            _diagnostic(
                "error",
                "report-integrity",
                "The canonical report changed after this OKF bundle was generated.",
            )
        )

    source_values = frontmatter.get("sources") or []
    if isinstance(source_values, dict):
        source_values = [source_values]
    if not isinstance(source_values, list):
        raise OkfArchiveError("OKF sources must be a list")
    if len(source_values) > MAX_SOURCES:
        raise OkfArchiveError("OKF source count exceeds the archive limit")

    citation_counts = _citation_counts(report)
    report_urls = set(_external_urls(report))
    seen_ids: set[str] = set()
    sources: list[dict[str, Any]] = []
    uncited_source_ids: list[str] = []
    missing_report_source_ids: list[str] = []
    for raw in source_values:
        if not isinstance(raw, dict):
            diagnostics.append(
                _diagnostic("error", "invalid-source", "A source record is invalid.")
            )
            continue
        source_id = str(raw.get("id") or "").strip()
        resource = _canonical_url(raw.get("resource"))
        if not SOURCE_ID.fullmatch(source_id) or source_id in seen_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "duplicate-source",
                    (
                        f"Source ID {source_id or '(missing)'} is invalid or "
                        "duplicated."
                    ),
                )
            )
            continue
        seen_ids.add(source_id)
        if resource is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "invalid-source-url",
                    f"Source {source_id} has an unsafe or malformed URL.",
                )
            )
            continue
        citations = citation_counts.get(source_id, 0)
        in_report = resource in report_urls
        health = "healthy" if citations and in_report else "warning"
        if not citations:
            uncited_source_ids.append(source_id)
        if not in_report:
            missing_report_source_ids.append(source_id)
        sources.append(
            {
                "id": source_id,
                "title": _source_title(raw.get("title"), resource),
                "resource": resource,
                "author": _one_line(raw.get("author"), 100),
                "last_modified": _date_string(raw.get("last_modified")),
                "citations": citations,
                "cited": citations > 0,
                "in_report": in_report,
                "health": health,
            }
        )

    if uncited_source_ids:
        diagnostics.append(
            _diagnostic(
                "warning",
                "uncited-source",
                (
                    f"{_counted(len(uncited_source_ids), 'source record')} "
                    f"{'has' if len(uncited_source_ids) == 1 else 'have'} no formal "
                    f"claim footnote: {_summarize(uncited_source_ids)}."
                ),
            )
        )
    if missing_report_source_ids:
        diagnostics.append(
            _diagnostic(
                "warning",
                "source-not-in-report",
                (
                    f"{_counted(len(missing_report_source_ids), 'source record')} "
                    f"{'is' if len(missing_report_source_ids) == 1 else 'are'} not "
                    "represented by an external URL in the canonical report: "
                    f"{_summarize(missing_report_source_ids)}."
                ),
            )
        )
    dangling = sorted(set(citation_counts) - seen_ids)
    if dangling:
        diagnostics.append(
            _diagnostic(
                "error",
                "unresolved-citation",
                (
                    f"{len(dangling)} formal claim footnote(s) have no matching "
                    f"source record: {_summarize(dangling)}."
                ),
            )
        )
    source_urls = {source["resource"] for source in sources}
    unmatched_report_urls = sorted(report_urls - source_urls)
    if unmatched_report_urls:
        diagnostics.append(
            _diagnostic(
                "warning",
                "unregistered-report-links",
                (
                    f"{len(unmatched_report_urls)} external report link(s) are not "
                    "represented in OKF provenance."
                ),
            )
        )
    compiler_warnings = release.get("warnings") or []
    if isinstance(compiler_warnings, list):
        diagnostics.extend(
            _diagnostic("warning", "compiler-warning", _one_line(item, 240))
            for item in compiler_warnings[:50]
            if _one_line(item, 240)
            and not (
                uncited_source_ids
                and str(item).startswith("Evidence sources not cited in report:")
            )
        )

    generated = frontmatter.get("generated")
    generated = generated if isinstance(generated, dict) else {}
    if frontmatter.get("generated") is not None and not generated.get("by"):
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid-generated",
                "Generated metadata must identify its producer.",
            )
        )
    if generated.get("at") and not _iso_datetime(generated.get("at")):
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid-generated",
                "Generated metadata has an invalid timestamp.",
            )
        )
    raw_verified = frontmatter.get("verified")
    verified = _verified(raw_verified)
    raw_events = (
        [raw_verified]
        if isinstance(raw_verified, dict)
        else raw_verified
        if isinstance(raw_verified, list)
        else []
    )
    if raw_verified is not None and (
        not isinstance(raw_events, list)
        or len(verified) != len(raw_events)
        or any(not event.get("at") for event in verified)
        or any(not _iso_datetime(event.get("at")) for event in verified)
    ):
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid-verification",
                "Verification metadata contains an invalid event.",
            )
        )
    trust = (
        "human-reviewed"
        if any(str(event.get("by") or "").startswith("human:") for event in verified)
        else "machine-confirmed"
        if verified
        else "unverified"
    )
    raw_stale_after = frontmatter.get("stale_after")
    stale_after = _date_string(raw_stale_after)
    if raw_stale_after and not stale_after:
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid-stale-after",
                "The stale-after value is not an ISO date.",
            )
        )
    stale = bool(
        stale_after
        and (today or datetime.now(UTC).date()) >= date.fromisoformat(stale_after)
    )
    registered_report_links = report_urls & source_urls
    coverage = (
        round(100 * len(registered_report_links) / len(report_urls))
        if report_urls
        else None
    )
    source_in_report_count = sum(source["in_report"] for source in sources)
    formally_cited_source_count = sum(source["cited"] for source in sources)
    source_presence_percent = (
        round(100 * source_in_report_count / len(sources)) if sources else None
    )
    citation_coverage_percent = (
        round(100 * formally_cited_source_count / len(sources)) if sources else None
    )
    status = str(frontmatter.get("status") or "stable")
    if status not in {"draft", "stable", "deprecated"}:
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid-status",
                f"Unsupported lifecycle status: {_one_line(status, 80)}",
            )
        )
    valid = not any(item["level"] == "error" for item in diagnostics)
    return {
        "valid": valid,
        "version": version,
        "type": concept_type,
        "title": _one_line(frontmatter.get("title") or "Research Report", 180),
        "description": _one_line(frontmatter.get("description"), 280),
        "status": status,
        "generated": {
            "by": _one_line(generated.get("by"), 120),
            "at": _one_line(generated.get("at"), 80),
        },
        "trust_tier": trust,
        "verified": verified,
        "stale_after": stale_after,
        "stale": stale,
        "integrity": (
            bundle_integrity
            and archive_integrity
            and artifact_integrity
            and report_integrity
        ),
        "bundle_integrity": bundle_integrity,
        "archive_integrity": archive_integrity,
        "artifact_integrity": artifact_integrity,
        "report_integrity": report_integrity,
        "bundle_sha256": actual_digest,
        "report_sha256": _one_line(release.get("source_report_sha256"), 64),
        "source_count": len(sources),
        "citation_count": sum(source["citations"] for source in sources),
        "formal_claim_citation_count": sum(citation_counts.values()),
        "formally_cited_source_count": formally_cited_source_count,
        "citation_coverage_percent": citation_coverage_percent,
        "report_link_count": len(report_urls),
        "registered_report_link_count": len(registered_report_links),
        "source_in_report_count": source_in_report_count,
        "source_presence_percent": source_presence_percent,
        "coverage_percent": coverage,
        "unmatched_report_urls": unmatched_report_urls[:50],
        "sources": sources,
        "diagnostics": _dedupe_diagnostics(diagnostics)[:100],
    }


def _validate_archive(
    content: bytes,
    artifact_digests: dict[str, str],
    loose_files: dict[str, bytes],
    diagnostics: list[dict[str, str]],
) -> bool:
    expected = {
        path.removeprefix("output/okf/"): digest
        for path, digest in artifact_digests.items()
        if path.startswith("output/okf/")
    }
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            safe = (
                len(infos) <= MAX_ARCHIVE_MEMBERS
                and len(names) == len(set(names))
                and set(names) == set(expected)
                and sum(info.file_size for info in infos) <= MAX_BUNDLE_BYTES
                and all(
                    not info.is_dir()
                    and not info.flag_bits & 0x1
                    and _safe_member(info.filename)
                    for info in infos
                )
            )
            if not safe:
                raise OkfArchiveError("OKF archive member contract is invalid")
            members = {info.filename: archive.read(info) for info in infos}
    except (OSError, RuntimeError, zipfile.BadZipFile, OkfArchiveError):
        diagnostics.append(
            _diagnostic(
                "error",
                "archive-contents",
                "The downloadable archive has unsafe or unexpected members.",
            )
        )
        return False
    valid = True
    for path, digest in expected.items():
        if hashlib.sha256(members[path]).hexdigest() != digest:
            valid = False
    for path, loose in loose_files.items():
        if members.get(path) != loose:
            valid = False
    if not valid:
        diagnostics.append(
            _diagnostic(
                "error",
                "archive-contents",
                "The downloadable archive does not match the validated concepts.",
            )
        )
    return valid


def _safe_member(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and "\\" not in value
        and "\x00" not in value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _source_title(value: object, resource: str) -> str:
    title = _one_line(value, 180)
    generic = re.sub(r"[^a-z]", "", title.casefold())
    return (
        resource
        if generic in {"", "http", "https", "url", "uri", "httpurl", "httpsurl"}
        else title
    )


def _parse_frontmatter(
    content: bytes,
    *,
    root_index: bool = False,
) -> tuple[dict[str, Any], str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OkfArchiveError("OKF document is not UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        if root_index:
            return {}, text
        raise OkfArchiveError("OKF concept has no frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise OkfArchiveError("OKF frontmatter is unterminated") from exc
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise OkfArchiveError("OKF frontmatter is invalid") from exc
    if not isinstance(frontmatter, dict):
        raise OkfArchiveError("OKF frontmatter must be a mapping")
    return frontmatter, "\n".join(lines[end + 1 :])


def _strict_json(content: bytes) -> Any:
    import json

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        content.decode("utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant {value}")
        ),
    )


def _citation_counts(body: str) -> dict[str, int]:
    result: dict[str, int] = {}
    fenced = False
    fence_marker = ""
    in_comment = False
    html_block = ""
    for line in body.splitlines():
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
        for source_id in FOOTNOTE_REF.findall(visible):
            result[source_id] = result.get(source_id, 0) + 1
    return result


def _external_urls(markdown: str) -> list[str]:
    result: list[str] = []
    fenced = False
    marker = ""
    for line in markdown.splitlines():
        stripped = line.lstrip()
        current = stripped[:3]
        if current in {"```", "~~~"}:
            if not fenced:
                fenced = True
                marker = current
            elif marker == current:
                fenced = False
            continue
        if fenced or line.startswith(("    ", "\t")):
            continue
        visible = _without_inline_code(line)
        for match in LINK.finditer(visible):
            if value := _canonical_url(match.group(1)):
                result.append(value)
        for match in AUTOLINK.finditer(visible):
            if value := _canonical_url(match.group(1)):
                result.append(value)
        bare_text = LINK.sub("", AUTOLINK.sub("", visible))
        for match in BARE_URL.finditer(bare_text):
            candidate = match.group(0).rstrip(".,;:!?)]}")
            if value := _canonical_url(candidate):
                result.append(value)
    return result


def _without_inline_code(line: str) -> str:
    parts = line.split("`")
    return "".join(
        part if index % 2 == 0 else " " * len(part)
        for index, part in enumerate(parts)
    )


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
    query_keys = {
        part.split("=", 1)[0].lower()
        for part in re.split(r"[&;]", _fully_unquote(parsed.query))
        if part
    }
    if query_keys & SENSITIVE_QUERY_KEYS:
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


def _verified(value: object) -> list[dict[str, str]]:
    values = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
    return [
        {
            "by": _one_line(item.get("by"), 120),
            "at": _one_line(item.get("at"), 80),
        }
        for item in values
        if isinstance(item, dict) and item.get("by")
    ][:20]


def _date_string(value: object) -> str:
    raw = str(value or "")[:10]
    try:
        return date.fromisoformat(raw).isoformat() if raw else ""
    except ValueError:
        return ""


def _iso_datetime(value: object) -> bool:
    raw = str(value or "")
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return bool(raw)


def _one_line(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _diagnostic(level: str, code: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message}


def _summarize(values: list[str], limit: int = 6) -> str:
    shown = ", ".join(values[:limit])
    remaining = len(values) - limit
    return f"{shown}, and {remaining} more" if remaining > 0 else shown


def _counted(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


def _dedupe_diagnostics(
    diagnostics: list[dict[str, str]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in diagnostics:
        key = (item["level"], item["code"], item["message"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
