"""Build a safe, self-contained in-app projection of a Markdown report."""

from __future__ import annotations

import asyncio
import base64
import io
import posixpath
import re
import warnings
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from huggingface_hub import HfFileSystem
from PIL import Image, UnidentifiedImageError

from .research_workspace import ResearchWorkspace

MAX_REPORT_IMAGES = 8
MAX_REPORT_IMAGE_BYTES = 2_000_000
MAX_REPORT_IMAGE_PAYLOAD_CHARS = 5_000_000
MAX_REPORT_IMAGE_PIXELS = 16_000_000

_IMAGE_RE = re.compile(
    r"(?<!\\)!\[(?P<alt>(?:\\.|[^\]])*)\]"
    r"\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>[^)\s]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_UNRESOLVED_IMAGE_RE = re.compile(r"(?<!\\)!\[")
_FENCE_RE = re.compile(r"(?m)^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\n]*(?:\n|$)")
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+).*?(?P=ticks)", re.DOTALL)
_INDENTED_CODE_RE = re.compile(r"(?m)(?:^(?: {4}|\t).*(?:\n|$))+")
_MEDIA_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

ImageReader = Callable[[ResearchWorkspace, str], Awaitable[bytes]]


async def build_report_preview(
    markdown: str,
    workspace: ResearchWorkspace,
    *,
    reader: ImageReader | None = None,
) -> list[dict[str, str]]:
    """Split Markdown into ordered text and embedded report-local image blocks."""
    blocks: list[dict[str, str]] = []
    cache: dict[str, tuple[str, str] | None] = {}
    cursor = 0
    payload_chars = 0
    image_count = 0

    protected = _protected_ranges(markdown)
    for match in _IMAGE_RE.finditer(markdown):
        if _is_protected(match.start(), protected):
            continue
        _append_markdown(blocks, markdown[cursor : match.start()])
        cursor = match.end()

        alt = _unescape_alt(match.group("alt")).strip() or "Report image"
        source = (match.group("angle") or match.group("plain") or "").strip()
        path = _safe_image_path(source)
        embedded: tuple[str, str] | None = None

        if path and image_count < MAX_REPORT_IMAGES:
            if path not in cache:
                try:
                    payload = await (reader or _read_image)(workspace, path)
                    media_type = _media_type(path, payload)
                    if (
                        media_type is None
                        or not payload
                        or len(payload) > MAX_REPORT_IMAGE_BYTES
                    ):
                        cache[path] = None
                    else:
                        cache[path] = (
                            media_type,
                            base64.b64encode(payload).decode("ascii"),
                        )
                except Exception:  # noqa: BLE001 - unavailable assets are nonfatal
                    cache[path] = None
            embedded = cache[path]

        if embedded is not None:
            encoded_chars = len(embedded[1])
            if payload_chars + encoded_chars > MAX_REPORT_IMAGE_PAYLOAD_CHARS:
                embedded = None
            else:
                payload_chars += encoded_chars

        if embedded is None:
            _append_markdown(blocks, f"\n\n> _Image unavailable: {alt}_\n\n")
            continue

        media_type, encoded = embedded
        blocks.append(
            {
                "kind": "image",
                "src": f"data:{media_type};base64,{encoded}",
                "alt": alt,
            }
        )
        image_count += 1

    _append_markdown(blocks, markdown[cursor:])
    return blocks or [{"kind": "markdown", "content": ""}]


def markdown_only_preview(markdown: str) -> list[dict[str, str]]:
    """Return a stable preview that cannot emit Markdown image elements."""
    content = _suppress_markdown_images(markdown)
    return [{"kind": "markdown", "content": content}]


def _append_markdown(blocks: list[dict[str, str]], content: str) -> None:
    content = _suppress_markdown_images(content)
    if not content:
        return
    if blocks and blocks[-1]["kind"] == "markdown":
        blocks[-1]["content"] += content
    else:
        blocks.append({"kind": "markdown", "content": content})


def _suppress_markdown_images(markdown: str) -> str:
    protected = _protected_ranges(markdown)
    return _UNRESOLVED_IMAGE_RE.sub(
        lambda match: (
            match.group(0) if _is_protected(match.start(), protected) else r"\!["
        ),
        markdown,
    )


def _protected_ranges(markdown: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while fence := _FENCE_RE.search(markdown, cursor):
        marker = fence.group("fence")
        close = re.search(
            rf"(?m)^[ \t]{{0,3}}{re.escape(marker[0])}{{{len(marker)},}}"
            r"[ \t]*(?:\n|$)",
            markdown[fence.end() :],
        )
        end = fence.end() + close.end() if close is not None else len(markdown)
        ranges.append((fence.start(), end))
        cursor = end

    for span in _CODE_SPAN_RE.finditer(markdown):
        if not _is_protected(span.start(), ranges):
            ranges.append((span.start(), span.end()))
    for block in _INDENTED_CODE_RE.finditer(markdown):
        if not _is_protected(block.start(), ranges):
            ranges.append((block.start(), block.end()))
    return sorted(ranges)


def _is_protected(offset: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _safe_image_path(source: str) -> str | None:
    if not source or "\\" in source or "\x00" in source:
        return None
    parsed = urlsplit(source)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    decoded = unquote(parsed.path)
    if decoded.startswith("/") or decoded != parsed.path:
        return None
    normalized = posixpath.normpath(decoded)
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        return None
    path = PurePosixPath(normalized)
    if path.suffix.lower() not in _MEDIA_TYPES:
        return None
    return path.as_posix()


def _media_type(path: str, payload: bytes) -> str | None:
    suffix = PurePosixPath(path).suffix.lower()
    expected = _MEDIA_TYPES.get(suffix)
    formats = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }
    if expected is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != formats[expected]:
                    return None
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width * height > MAX_REPORT_IMAGE_PIXELS
                ):
                    return None
                image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return None
    return expected


async def _read_image(workspace: ResearchWorkspace, path: str) -> bytes:
    def read() -> bytes:
        filesystem = HfFileSystem(token=workspace.bearer_token)
        with filesystem.open(f"{workspace.output}{path}", "rb") as image:
            return bytes(image.read(MAX_REPORT_IMAGE_BYTES + 1))

    return await asyncio.to_thread(read)


def _unescape_alt(alt: str) -> str:
    return re.sub(r"\\([\\\[\]])", r"\1", alt)
