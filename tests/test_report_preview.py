from __future__ import annotations

import base64
import io
import random

import pytest
from PIL import Image

from research.report_preview import (
    MAX_REPORT_IMAGE_PAYLOAD_CHARS,
    build_report_preview,
    markdown_only_preview,
)
from research.research_workspace import ResearchWorkspace


def image_bytes(format_: str, *, size: tuple[int, int] = (2, 2)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "#ff9d0b").save(output, format=format_)
    return output.getvalue()


PNG = image_bytes("PNG")
JPEG = image_bytes("JPEG")
HF_BUCKET_PATH = "huggingface.co/buckets/alice/research-agent"
HF_BUCKET_PORT_PATH = "huggingface.co:443/buckets/alice/research-agent"
OTHER_BUCKET_PATH = "huggingface.co/buckets/bob/research-agent"
WORKSPACE_RESOLVE_URL = f"https://{HF_BUCKET_PATH}/resolve/research-abc/"


def workspace() -> ResearchWorkspace:
    return ResearchWorkspace(
        username="alice",
        session_id="research-abc",
        bucket_id="alice/research-agent",
        root="hf://buckets/alice/research-agent/research-abc/",
        scratch="hf://buckets/alice/research-agent/research-abc/scratch/",
        output="hf://buckets/alice/research-agent/research-abc/output/",
        bucket_created=False,
        marker_paths=(),
        bearer_token="token",
    )


@pytest.mark.asyncio
async def test_report_images_are_embedded_in_document_order() -> None:
    reads: list[str] = []

    async def read(current: ResearchWorkspace, path: str) -> bytes:
        assert current.bearer_token == "token"
        reads.append(path)
        return {"output/chart.png": PNG, "output/assets/detail.jpg": JPEG}[path]

    blocks = await build_report_preview(
        (
            "# Results\n\nBefore.\n\n"
            "![Overview](chart.png)\n\nBetween.\n\n"
            "![Detail](assets/detail.jpg)\n\nAfter."
        ),
        workspace(),
        reader=read,
    )

    assert [block["kind"] for block in blocks] == [
        "markdown",
        "image",
        "markdown",
        "image",
        "markdown",
    ]
    assert reads == ["output/chart.png", "output/assets/detail.jpg"]
    assert blocks[1] == {
        "kind": "image",
        "src": f"data:image/png;base64,{base64.b64encode(PNG).decode()}",
        "alt": "Overview",
    }
    assert blocks[3]["src"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_unsafe_missing_and_unsupported_images_never_reach_markdown() -> None:
    reads: list[str] = []

    async def read(_: ResearchWorkspace, path: str) -> bytes:
        reads.append(path)
        raise FileNotFoundError(path)

    blocks = await build_report_preview(
        "![Missing](missing.png)\n"
        "![Traversal](../secret.png)\n"
        "![Remote](https://example.com/chart.png)\n"
        "![Vector](chart.svg)\n"
        "![Reference][chart]\n"
        "[chart]: relative.png",
        workspace(),
        reader=read,
    )
    content = "".join(
        block.get("content", "") for block in blocks if block["kind"] == "markdown"
    )

    assert reads == ["output/missing.png"]
    assert not any(block["kind"] == "image" for block in blocks)
    assert "Image unavailable: Missing" in content
    assert "Image unavailable: Traversal" in content
    assert "Image unavailable: Remote" in content
    assert "Image unavailable: Vector" in content
    assert r"\![Reference][chart]" in content


@pytest.mark.asyncio
async def test_image_syntax_in_code_is_not_fetched_or_modified() -> None:
    markdown = (
        "Inline `![example](inline.png)`.\n\n```md\n![example](fenced.png)\n```\n"
        "\n    ![example](indented.png)\n"
    )

    async def fail(_: ResearchWorkspace, path: str) -> bytes:
        raise AssertionError(f"unexpected read: {path}")

    blocks = await build_report_preview(markdown, workspace(), reader=fail)

    assert blocks == [{"kind": "markdown", "content": markdown}]


@pytest.mark.asyncio
async def test_repeated_images_respect_serialized_payload_limit() -> None:
    pixels = random.Random(0).randbytes(512 * 512 * 3)
    noisy = Image.frombytes("RGB", (512, 512), pixels)
    output = io.BytesIO()
    noisy.save(output, format="PNG")
    payload = output.getvalue()
    assert len(payload) < 2_000_000

    reads = 0

    async def read(_: ResearchWorkspace, path: str) -> bytes:
        nonlocal reads
        assert path == "output/chart.png"
        reads += 1
        return payload

    blocks = await build_report_preview(
        "\n".join("![Chart](chart.png)" for _ in range(8)),
        workspace(),
        reader=read,
    )

    encoded = sum(
        len(block.get("src", "")) for block in blocks if block["kind"] == "image"
    )
    assert reads == 1
    assert encoded <= MAX_REPORT_IMAGE_PAYLOAD_CHARS + 30 * 8
    assert any("Image unavailable" in block.get("content", "") for block in blocks)


@pytest.mark.asyncio
async def test_corrupt_image_is_replaced_with_fallback() -> None:
    async def read(_: ResearchWorkspace, __: str) -> bytes:
        return b"\x89PNG\r\n\x1a\nnot-an-image"

    blocks = await build_report_preview(
        "![Chart](chart.png)",
        workspace(),
        reader=read,
    )

    assert blocks == [
        {"kind": "markdown", "content": "\n\n> _Image unavailable: Chart_\n\n"}
    ]


def test_markdown_only_preview_suppresses_image_elements() -> None:
    assert markdown_only_preview("![Chart](chart.png)") == [
        {"kind": "markdown", "content": r"\![Chart](chart.png)"}
    ]


@pytest.mark.asyncio
async def test_same_workspace_bucket_url_is_embedded() -> None:
    reads: list[str] = []

    async def read(_: ResearchWorkspace, path: str) -> bytes:
        reads.append(path)
        return PNG

    blocks = await build_report_preview(
        (
            "![Chart](https://huggingface.co/buckets/alice/research-agent/"
            "resolve/research-abc/scratch/research/chart.png)"
        ),
        workspace(),
        reader=read,
    )

    assert reads == ["scratch/research/chart.png"]
    assert blocks[0]["kind"] == "image"
    assert blocks[0]["src"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_same_workspace_bucket_main_revision_url_is_embedded() -> None:
    reads: list[str] = []

    async def read(_: ResearchWorkspace, path: str) -> bytes:
        reads.append(path)
        return PNG

    blocks = await build_report_preview(
        (
            "![Chart](https://huggingface.co/buckets/alice/research-agent/"
            "resolve/main/research-abc/scratch/research/chart.png)"
        ),
        workspace(),
        reader=read,
    )

    assert reads == ["scratch/research/chart.png"]
    assert blocks[0]["kind"] == "image"


@pytest.mark.asyncio
async def test_same_workspace_tree_url_is_embedded() -> None:
    reads: list[str] = []

    async def read(_: ResearchWorkspace, path: str) -> bytes:
        reads.append(path)
        return PNG

    blocks = await build_report_preview(
        (
            "![Chart](https://huggingface.co/buckets/alice/research-agent/"
            "tree/research-abc/output/assets/chart.png)"
        ),
        workspace(),
        reader=read,
    )

    assert reads == ["output/assets/chart.png"]
    assert blocks[0]["kind"] == "image"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    (
        f"http://{HF_BUCKET_PATH}/resolve/research-abc/scratch/chart.png",
        f"https://www.{HF_BUCKET_PATH}/resolve/research-abc/scratch/chart.png",
        f"https://{HF_BUCKET_PORT_PATH}/resolve/research-abc/scratch/chart.png",
        f"https://{OTHER_BUCKET_PATH}/resolve/research-abc/scratch/chart.png",
        f"https://{HF_BUCKET_PATH}/resolve/other-session/scratch/chart.png",
        f"{WORKSPACE_RESOLVE_URL}../other-session/chart.png",
        f"{WORKSPACE_RESOLVE_URL}%2e%2e%2fother-session%2fchart.png",
        f"{WORKSPACE_RESOLVE_URL}private/chart.png",
        f"{WORKSPACE_RESOLVE_URL}scratch/chart.png?download=true",
        f"{WORKSPACE_RESOLVE_URL}scratch/chart.png#part",
        f"{WORKSPACE_RESOLVE_URL}scratch/chart.svg",
    ),
)
async def test_other_bucket_urls_are_rejected(source: str) -> None:
    async def fail(_: ResearchWorkspace, path: str) -> bytes:
        raise AssertionError(f"unexpected read: {path}")

    blocks = await build_report_preview(
        f"![Chart]({source})",
        workspace(),
        reader=fail,
    )

    assert blocks == [
        {"kind": "markdown", "content": "\n\n> _Image unavailable: Chart_\n\n"}
    ]
