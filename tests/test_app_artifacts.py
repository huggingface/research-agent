from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fast_agent import AgentAuth

from research.app_artifacts import MARKER, finalize_bucket_html, read_bucket_markdown
from research.app_jobs import ResearchJob


class BucketSimulator:
    def __init__(self, draft: str) -> None:
        self.draft = draft
        self.uploaded: bytes | None = None
        self.output_path: str | None = None

    def whoami(self, *, token: str) -> dict[str, str]:
        return {"name": "alice"}

    def download_bucket_files(
        self,
        bucket_id: str,
        files: list[tuple[str, Path]],
        **kwargs: Any,
    ) -> None:
        remote, local = files[0]
        assert remote.endswith("/scratch/report.html")
        local.write_text(self.draft)

    def batch_bucket_files(
        self,
        bucket_id: str,
        *,
        add: list[tuple[bytes, str]],
        token: str,
    ) -> None:
        self.uploaded, self.output_path = add[0]


class MarkdownBucketSimulator:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown
        self.tokens: list[str] = []

    def whoami(self, *, token: str) -> dict[str, str]:
        self.tokens.append(token)
        return {"name": "alice"}

    def download_bucket_files(
        self,
        bucket_id: str,
        files: list[tuple[str, Path]],
        *,
        token: str,
        **kwargs: Any,
    ) -> None:
        self.tokens.append(token)
        remote, local = files[0]
        assert bucket_id == "alice/research-agent"
        assert remote == "research-123/output/report.md"
        local.write_text(self.markdown)


class PresentationBucketSimulator:
    def __init__(
        self,
        draft: str,
        *,
        asset_path: str | None = "assets/chart.png",
        media_type: str = "image/png",
    ) -> None:
        self.draft = draft
        self.asset_path = asset_path
        self.media_type = media_type
        self.uploads: list[tuple[bytes, str]] = []

    def whoami(self, *, token: str) -> dict[str, str]:
        return {"name": "alice"}

    def list_bucket_tree(self, *args: Any, **kwargs: Any) -> list[object]:
        return []

    def download_bucket_files(
        self,
        bucket_id: str,
        files: list[tuple[str, Path]],
        **kwargs: Any,
    ) -> None:
        remote, local = files[0]
        if remote.endswith("/report.html"):
            local.write_text(self.draft)
        elif remote.endswith("/manifest.json"):
            artifacts = [
                {
                    "path": "scratch/presentation/attempts/1/report.html",
                    "media_type": "text/html",
                }
            ]
            if self.asset_path:
                artifacts.append(
                    {
                        "path": (f"scratch/presentation/attempts/1/{self.asset_path}"),
                        "media_type": self.media_type,
                    }
                )
            local.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stage": "presentation",
                        "attempt": 1,
                        "status": "complete",
                        "entrypoint": ("scratch/presentation/attempts/1/report.html"),
                        "artifacts": artifacts,
                    }
                )
            )
        elif remote.endswith("/assets/chart.png"):
            local.write_bytes(b"\x89PNG\r\n\x1a\nchart")
        else:
            raise FileNotFoundError(remote)

    def batch_bucket_files(
        self,
        bucket_id: str,
        *,
        add: list[tuple[bytes, str]],
        token: str,
    ) -> None:
        self.uploads = add


def test_finalizer_injects_css_and_preserves_source_links(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root { --accent: #abc; } .page { color: black; }")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page"><a href="https://example.com/source">Source</a></main></body>
</html>"""
    api = BucketSimulator(draft)
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    auth = AgentAuth.bearer("token", subject="alice")

    urls = finalize_bucket_html(
        job,
        auth,
        tmp_path,
        api=api,  # type: ignore[arg-type]
    )

    assert urls == (
        "hf://buckets/alice/research-agent/research-123/output/report.html",
        "https://huggingface.co/buckets/alice/research-agent/tree/"
        "research-123/output/report.html",
    )
    output = api.uploaded.decode() if api.uploaded else ""
    assert MARKER not in output
    assert "--accent: #abc" in output
    assert 'href="https://example.com/source"' in output
    assert api.output_path == "research-123/output/report.html"


def test_finalizer_normalizes_generic_marker_style(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root { --accent: #abc; }")
    draft = f"""<!doctype html>
<html><head><style>
{MARKER}
</style></head><body><main class="stack">Report</main></body></html>"""
    api = BucketSimulator(draft)
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    auth = AgentAuth.bearer("token", subject="alice")

    finalize_bucket_html(job, auth, tmp_path, api=api)  # type: ignore[arg-type]

    output = api.uploaded.decode() if api.uploaded else ""
    assert "<style data-birch-system>" in output
    assert '<main class="page stack">' in output
    assert MARKER not in output
    assert "--accent: #abc" in output


def test_finalizer_promotes_declared_presentation_assets(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root { --accent: #abc; } .page { color: black; }")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page"><img src="assets/chart.png" alt="Chart"></main></body>
</html>"""
    api = PresentationBucketSimulator(draft)
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    job.birch_finalize_attempts = 1

    finalize_bucket_html(
        job,
        AgentAuth.bearer("token", subject="alice"),
        tmp_path,
        api=api,  # type: ignore[arg-type]
        required=True,
    )

    paths = [path for _, path in api.uploads]
    assert paths == [
        "research-123/output/report.html",
        "research-123/output/assets/chart.png",
    ]
    assert api.uploads[1][0].startswith(b"\x89PNG")
    finalized = api.uploads[0][0].decode()
    assert 'src="data:image/png;base64,' in finalized
    assert 'src="assets/chart.png"' not in finalized


def test_finalizer_rejects_markdown_as_presentation_asset(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root {}")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page"><a href="assets/report.md">Report</a></main></body>
</html>"""
    api = PresentationBucketSimulator(draft, asset_path="assets/report.md")
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    job.birch_finalize_attempts = 1

    with pytest.raises(
        ValueError,
        match=r'output/report\.md is already published.*href="report\.md"',
    ):
        finalize_bucket_html(
            job,
            AgentAuth.bearer("token", subject="alice"),
            tmp_path,
            api=api,  # type: ignore[arg-type]
            required=True,
        )

    assert not api.uploads


def test_finalizer_rejects_mismatched_asset_media_type(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root {}")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page"><img src="assets/chart.png"></main></body></html>"""
    api = PresentationBucketSimulator(draft, media_type="text/plain")
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    job.birch_finalize_attempts = 1

    with pytest.raises(ValueError, match="declares media type"):
        finalize_bucket_html(
            job,
            AgentAuth.bearer("token", subject="alice"),
            tmp_path,
            api=api,  # type: ignore[arg-type]
            required=True,
        )


def test_finalizer_preserves_canonical_sibling_markdown_link(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root {}")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page"><a href="report.md">Markdown</a></main></body></html>"""
    api = PresentationBucketSimulator(draft, asset_path=None)
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    job.birch_finalize_attempts = 1

    finalize_bucket_html(
        job,
        AgentAuth.bearer("token", subject="alice"),
        tmp_path,
        api=api,  # type: ignore[arg-type]
        required=True,
    )

    assert 'href="report.md"' in api.uploads[0][0].decode()


def test_markdown_reader_uses_callers_token() -> None:
    api = MarkdownBucketSimulator("# Findings\n\n[Source](https://example.com)")
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    auth = AgentAuth.bearer("caller-token", subject="alice")

    markdown = read_bucket_markdown(job, auth, api=api)  # type: ignore[arg-type]

    assert markdown.startswith("# Findings")
    assert api.tokens == ["caller-token", "caller-token"]


def test_required_finalizer_rejects_missing_auth(tmp_path: Path) -> None:
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")

    with pytest.raises(
        RuntimeError,
        match="Caller authentication is required",
    ):
        finalize_bucket_html(job, None, tmp_path, required=True)


def test_artifacts_use_readable_workspace_id(tmp_path: Path) -> None:
    css_path = tmp_path / "skills" / "birch-html" / "assets" / "birch-system.css"
    css_path.parent.mkdir(parents=True)
    css_path.write_text(":root { --accent: #abc; }")
    draft = f"""<!doctype html>
<html><head><style data-birch-system>{MARKER}</style></head>
<body><main class="page">Report</main></body></html>"""
    api = BucketSimulator(draft)
    job = ResearchJob(
        id="research-123",
        topic="topic",
        owner_id="alice",
        workspace_id="26-07-21-readable-brief-a123",
    )

    urls = finalize_bucket_html(
        job,
        AgentAuth.bearer("token", subject="alice"),
        tmp_path,
        api=api,  # type: ignore[arg-type]
    )

    assert urls[0].endswith("/26-07-21-readable-brief-a123/output/report.html")
    assert api.output_path == "26-07-21-readable-brief-a123/output/report.html"
