#!/usr/bin/env python3
"""Publish safe report artifacts to a separate public bucket and archive."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import unquote, urlsplit

from huggingface_hub import HfApi, HfFileSystem, Volume, get_token
from huggingface_hub.errors import BucketNotFoundError, RepositoryNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.okf_compiler import build_public_okf_release

SOURCE_BUCKET = "evalstate/research-agent"
PUBLIC_BUCKET = "evalstate/researcher-reports-public"
PUBLIC_SPACE = "evalstate/researcher-reports"
TEMPLATE_SPACE = "evalstate/research-archive-template"
MOUNT_PATH = "/research"
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_MEDIA = {".css", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
HF_TOKEN = re.compile(rb"hf_[A-Za-z0-9]{20,}")
HF_TOKEN_TEXT = re.compile(r"hf_[A-Za-z0-9]{20,}")
URL = re.compile(r"(?:https?|hf)://[^\s<>\"'`]+", re.IGNORECASE)
CSS_ESCAPE = re.compile(
    r"\\([0-9A-Fa-f]{1,6})(?:\r\n|[ \t\r\n\f])?|\\([^\r\n\f0-9A-Fa-f])"
)
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
KNOWLEDGE_MANIFEST = "scratch/knowledge/manifest.json"


class PublicationError(RuntimeError):
    """A report publication operation was unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class Artifact:
    run_id: str
    relative_path: str
    source_path: str
    size: int


def bucket_path(bucket_id: str) -> str:
    return f"buckets/{bucket_id}"


def is_public_artifact(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if (
        path == PurePosixPath("output/okf.zip")
        or path.parts[:2] == ("output", "okf")
    ):
        return False
    if path in {
        PurePosixPath("output/report.md"),
        PurePosixPath("output/report.html"),
    }:
        return True
    if len(path.parts) < 2 or path.parts[0] != "output":
        return False
    if path.suffix.lower() not in SAFE_MEDIA:
        return False
    return len(path.parts) == 2 or path.parts[1] == "assets"


def discover_artifacts(
    fs: HfFileSystem,
    source_bucket: str,
    run_ids: Iterable[str] | None,
) -> list[Artifact]:
    requested = set(run_ids or ())
    for run_id in requested:
        if not SAFE_SEGMENT.fullmatch(run_id):
            raise PublicationError(f"Unsafe run ID: {run_id!r}")

    root = bucket_path(source_bucket)
    found: list[Artifact] = []
    search_roots = [f"{root}/{run_id}/output" for run_id in sorted(requested)]
    if not search_roots:
        search_roots = [root]
    for search_root in search_roots:
        try:
            entries = fs.find(search_root, detail=True)
        except FileNotFoundError:
            continue
        for path, info in entries.items():
            if info.get("type") != "file" or not path.startswith(f"{root}/"):
                continue
            run_id, separator, relative_path = path.removeprefix(f"{root}/").partition(
                "/"
            )
            if not separator or (requested and run_id not in requested):
                continue
            if is_public_artifact(relative_path):
                found.append(
                    Artifact(
                        run_id=run_id,
                        relative_path=relative_path,
                        source_path=path,
                        size=int(info.get("size", 0)),
                    )
                )

    by_run: dict[str, set[str]] = {}
    for artifact in found:
        by_run.setdefault(artifact.run_id, set()).add(artifact.relative_path)
    selected = requested or set(by_run)
    missing = selected - set(by_run)
    incomplete = {
        run_id
        for run_id in selected & set(by_run)
        if not {
            "output/report.md",
            "output/report.html",
        }.issubset(by_run[run_id])
    }
    if missing:
        raise PublicationError(f"Runs not found: {', '.join(sorted(missing))}")
    if incomplete:
        raise PublicationError(
            f"Runs missing report.md or report.html: {', '.join(sorted(incomplete))}"
        )
    return sorted(found, key=lambda item: (item.run_id, item.relative_path))


def digest(stream: BinaryIO) -> bytes:
    value = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        value.update(chunk)
    return value.digest()


def public_bytes(
    fs: HfFileSystem,
    artifact: Artifact,
    source_bucket: str,
    destination_bucket: str,
) -> bytes:
    with fs.open(artifact.source_path, "rb") as source:
        content = source.read()
    suffix = PurePosixPath(artifact.relative_path).suffix.lower()
    if artifact.relative_path in {"output/report.md", "output/report.html"}:
        content = (
            content.replace(
                f"https://huggingface.co/buckets/{source_bucket}".encode(),
                f"https://huggingface.co/buckets/{destination_bucket}".encode(),
            )
            .replace(
                f"hf://buckets/{source_bucket}".encode(),
                f"hf://buckets/{destination_bucket}".encode(),
            )
            .replace(
                f"huggingface.co/buckets/{source_bucket}".encode(),
                f"huggingface.co/buckets/{destination_bucket}".encode(),
            )
        )
        _validate_public_content(
            content,
            source_bucket,
            f"{artifact.run_id}/{artifact.relative_path}",
        )
    elif suffix in {".css", ".svg"}:
        _validate_public_content(
            content,
            source_bucket,
            f"{artifact.run_id}/{artifact.relative_path}",
        )
    elif source_bucket.encode() in content:
        raise PublicationError(
            f"{artifact.run_id}/{artifact.relative_path} still references the "
            "private source bucket."
        )
    if artifact.relative_path in {
        "output/report.md",
        "output/report.html",
    } and _references_private_okf(content):
        raise PublicationError(
            f"{artifact.run_id}/{artifact.relative_path} references a private "
            "OKF bundle."
        )
    if HF_TOKEN.search(content):
        raise PublicationError(
            f"{artifact.run_id}/{artifact.relative_path} looks like it contains "
            "a Hugging Face token."
        )
    return content


def _references_private_okf(content: bytes) -> bool:
    text = _decoded_text(content)
    normalized = re.sub(r"/+", "/", text.replace("\\", "/").lower())
    return bool(re.search(r"(?:^|/)output/okf(?:\.zip|/)", normalized))


def _decoded_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="ignore")
    while True:
        decoded = _decode_css_escapes(unquote(html.unescape(text)))
        if decoded == text:
            return text
        text = decoded


def _decode_css_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if escaped := match.group(1):
            codepoint = int(escaped, 16)
            return (
                chr(codepoint)
                if codepoint and codepoint <= 0x10FFFF
                else "\N{REPLACEMENT CHARACTER}"
            )
        return match.group(2)

    return CSS_ESCAPE.sub(replace, value)


def _validate_public_content(
    content: bytes,
    source_bucket: str,
    label: str,
) -> None:
    text = _decoded_text(content)
    if source_bucket.casefold() in text.replace("\\", "/").casefold():
        raise PublicationError(f"{label} still references the private source bucket.")
    if HF_TOKEN_TEXT.search(text):
        raise PublicationError(f"{label} looks like it contains a Hugging Face token.")
    for match in URL.finditer(text):
        raw = match.group().rstrip(".,;:!?)]}")
        parsed = urlsplit(raw)
        if parsed.username or parsed.password:
            raise PublicationError(f"{label} contains URL credentials.")
        keys = {
            unquote(part.partition("=")[0]).strip().casefold()
            for part in re.split(r"[&;]", parsed.query)
            if part
        }
        if keys & SENSITIVE_QUERY_KEYS:
            raise PublicationError(f"{label} contains a sensitive URL query.")


def prepare_public_evidence(
    prepared: list[tuple[str, str, bytes]],
    source_bucket: str,
) -> list[tuple[str, str, bytes]]:
    reports = {
        run_id: content
        for run_id, relative_path, content in prepared
        if relative_path == "output/report.md"
    }
    result: list[tuple[str, str, bytes]] = []
    for run_id, report in sorted(reports.items()):
        try:
            release = build_public_okf_release(report, workspace_id=run_id)
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublicationError(
                f"{run_id}/output/report.md could not produce public evidence."
            ) from exc
        _validate_public_evidence(release, source_bucket)
        result.extend(
            (run_id, relative_path, content)
            for relative_path, content in sorted(release.items())
        )
    return result


def _validate_public_evidence(
    release: dict[str, bytes],
    source_bucket: str,
) -> None:
    values = [
        content
        for path, content in release.items()
        if path != "output/okf.zip"
    ]
    try:
        with zipfile.ZipFile(io.BytesIO(release["output/okf.zip"])) as archive:
            values.extend(archive.read(name) for name in archive.namelist())
    except (KeyError, zipfile.BadZipFile) as exc:
        raise PublicationError("Generated public evidence bundle was invalid.") from exc
    for content in values:
        _validate_public_content(content, source_bucket, "Generated public evidence")
        if HF_TOKEN.search(content):
            raise PublicationError(
                "Generated public evidence looks like it contains a Hugging Face token."
            )


def artifact_changed(
    fs: HfFileSystem,
    content: bytes,
    destination: str,
) -> bool:
    try:
        info = fs.info(destination)
    except FileNotFoundError:
        return True
    if int(info.get("size", -1)) != len(content):
        return True
    with fs.open(destination, "rb") as target:
        return hashlib.sha256(content).digest() != digest(target)


def batch_upload(
    api: HfApi,
    bucket_id: str,
    additions: list[tuple[bytes, str]],
    token: str,
) -> None:
    if additions:
        api.batch_bucket_files(bucket_id, add=additions, token=token)


def publish_prepared(
    api: HfApi,
    fs: HfFileSystem,
    bucket_id: str,
    prepared: list[tuple[str, str, bytes]],
    evidence_runs: set[str],
    token: str,
) -> list[str]:
    root = bucket_path(bucket_id)
    regular: list[tuple[bytes, str]] = []
    manifests: dict[str, tuple[bytes, str, bool]] = {}
    changed_runs: set[str] = set()
    for run_id, relative_path, content in prepared:
        relative_destination = f"{run_id}/{relative_path}"
        destination = f"{root}/{relative_destination}"
        changed = artifact_changed(fs, content, destination)
        if relative_path == KNOWLEDGE_MANIFEST:
            manifests[run_id] = (content, relative_destination, changed)
            continue
        if changed:
            if (
                relative_path == "output/report.md"
                and run_id not in evidence_runs
                and _exists(fs, f"{root}/{run_id}/{KNOWLEDGE_MANIFEST}")
            ):
                raise PublicationError(
                    f"{run_id} already has public evidence; republish it with "
                    "--include-evidence."
                )
            regular.append((content, relative_destination))
            if run_id in evidence_runs:
                changed_runs.add(run_id)

    stale_manifests = [
        f"{run_id}/{KNOWLEDGE_MANIFEST}"
        for run_id in sorted(changed_runs)
        if _exists(fs, f"{root}/{run_id}/{KNOWLEDGE_MANIFEST}")
    ]
    if stale_manifests:
        api.batch_bucket_files(bucket_id, delete=stale_manifests, token=token)
    batch_upload(api, bucket_id, regular, token)

    manifest_additions = [
        (content, destination)
        for run_id, (content, destination, changed) in sorted(manifests.items())
        if changed or run_id in changed_runs
    ]
    batch_upload(api, bucket_id, manifest_additions, token)
    return [
        destination
        for _, destination in [*regular, *manifest_additions]
    ]


def _exists(fs: HfFileSystem, path: str) -> bool:
    try:
        fs.info(path)
    except FileNotFoundError:
        return False
    return True


def ensure_public_bucket(api: HfApi, bucket_id: str, token: str) -> bool:
    try:
        info = api.bucket_info(bucket_id, token=token)
    except BucketNotFoundError:
        api.create_bucket(bucket_id, private=False, exist_ok=False, token=token)
        return True
    if info.private:
        raise PublicationError(
            f"Destination bucket {bucket_id!r} exists but is private; refusing "
            "to change its visibility."
        )
    return False


def _read_marker(api: HfApi, space_id: str, token: str) -> dict[str, Any]:
    try:
        path = api.hf_hub_download(
            space_id,
            "archive-template.json",
            repo_type="space",
            token=token,
            force_download=True,
        )
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except Exception as exc:
        raise PublicationError(
            f"Space {space_id!r} is not a managed Research Archive."
        ) from exc


def _validate_marker(marker: dict[str, Any], space_id: str) -> None:
    if (
        marker.get("schema_version") != 1
        or marker.get("managed_by") != "research-agent"
        or marker.get("template") != "research-archive"
    ):
        raise PublicationError(f"Space {space_id!r} is not a managed Research Archive.")


def _has_public_volume(info: Any, bucket_id: str) -> bool:
    runtime = getattr(info, "runtime", None)
    raw = getattr(runtime, "raw", None)
    volumes = raw.get("volumes", []) if isinstance(raw, dict) else []
    return any(
        volume.get("type") == "bucket"
        and volume.get("source") == bucket_id
        and volume.get("mountPath") == MOUNT_PATH
        and volume.get("readOnly") is True
        for volume in volumes
        if isinstance(volume, dict)
    )


def _ensure_variable(
    api: HfApi, space_id: str, key: str, value: str, token: str
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
    if current_value != value:
        api.add_space_variable(space_id, key, value, token=token)


def ensure_public_space(
    api: HfApi,
    *,
    space_id: str,
    bucket_id: str,
    template_space: str,
    token: str,
) -> bool:
    volume = Volume(
        type="bucket",
        source=bucket_id,
        mount_path=MOUNT_PATH,
        read_only=True,
    )
    try:
        info = api.space_info(space_id, token=token)
    except RepositoryNotFoundError:
        marker = _read_marker(api, template_space, token)
        _validate_marker(marker, template_space)
        api.duplicate_repo(
            from_id=template_space,
            to_id=space_id,
            repo_type="space",
            private=False,
            exist_ok=False,
            space_hardware="cpu-basic",
            space_volumes=[volume],
            space_variables=[
                {"key": "RESEARCH_ARCHIVE_READ_ONLY", "value": "true"},
                {"key": "RESEARCH_ARCHIVE_BUCKET", "value": bucket_id},
            ],
            token=token,
        )
        return True

    if info.private:
        raise PublicationError(
            f"Destination Space {space_id!r} exists but is private; refusing "
            "to change its visibility."
        )
    _validate_marker(_read_marker(api, space_id, token), space_id)
    if not _has_public_volume(info, bucket_id):
        api.set_space_volumes(space_id, [volume], token=token)
    _ensure_variable(api, space_id, "RESEARCH_ARCHIVE_READ_ONLY", "true", token)
    _ensure_variable(api, space_id, "RESEARCH_ARCHIVE_BUCKET", bucket_id, token)
    return False


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source", default=SOURCE_BUCKET)
    result.add_argument("--destination", default=PUBLIC_BUCKET)
    result.add_argument("--space", default=PUBLIC_SPACE)
    result.add_argument("--template", default=TEMPLATE_SPACE)
    selection = result.add_mutually_exclusive_group(required=True)
    selection.add_argument("--run", action="append", dest="runs")
    selection.add_argument("--all", action="store_true")
    result.add_argument(
        "--publish",
        action="store_true",
        help="Create/update public resources; otherwise perform a dry run.",
    )
    result.add_argument(
        "--include-evidence",
        action="store_true",
        help="Generate a public-safe OKF release from sanitized report Markdown.",
    )
    return result


def validate_selection(args: argparse.Namespace) -> None:
    if args.include_evidence and args.all:
        raise PublicationError(
            "Public evidence requires explicit --run selections; --all is refused."
        )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    validate_selection(args)
    token = get_token()
    if not token:
        raise PublicationError("Log in with `hf auth login` before publishing.")
    api = HfApi(token=token)
    fs = HfFileSystem(token=token)
    artifacts = discover_artifacts(fs, args.source, args.runs if not args.all else None)
    prepared = [
        (
            artifact.run_id,
            artifact.relative_path,
            public_bytes(fs, artifact, args.source, args.destination),
        )
        for artifact in artifacts
    ]
    runs = sorted({artifact.run_id for artifact in artifacts})
    if args.include_evidence:
        prepared.extend(prepare_public_evidence(prepared, args.source))
    total = sum(len(content) for _, _, content in prepared)
    mode = "PUBLISH" if args.publish else "DRY RUN"
    print(f"{mode}: {len(runs)} runs, {len(prepared)} files, {total:,} bytes")
    print(f"  source:      hf://buckets/{args.source}")
    print(f"  destination: hf://buckets/{args.destination}")
    print(f"  archive:     https://huggingface.co/spaces/{args.space}")

    if not args.publish:
        for run_id in runs:
            print(f"  would publish {run_id}")
        return 0

    created_bucket = ensure_public_bucket(api, args.destination, token)
    changed = publish_prepared(
        api,
        fs,
        args.destination,
        prepared,
        set(runs) if args.include_evidence else set(),
        token,
    )
    for destination in changed:
        print(f"  copied {destination}")
    created_space = ensure_public_space(
        api,
        space_id=args.space,
        bucket_id=args.destination,
        template_space=args.template,
        token=token,
    )
    print(
        f"Published {len(runs)} runs; {len(changed)} files changed "
        f"(bucket {'created' if created_bucket else 'reused'}, "
        f"Space {'created' if created_space else 'reused'})."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
