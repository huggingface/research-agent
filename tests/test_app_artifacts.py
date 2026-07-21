from __future__ import annotations

from pathlib import Path
from typing import Any

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


def test_markdown_reader_uses_callers_token() -> None:
    api = MarkdownBucketSimulator("# Findings\n\n[Source](https://example.com)")
    job = ResearchJob(id="research-123", topic="topic", owner_id="alice")
    auth = AgentAuth.bearer("caller-token", subject="alice")

    markdown = read_bucket_markdown(job, auth, api=api)  # type: ignore[arg-type]

    assert markdown.startswith("# Findings")
    assert api.tokens == ["caller-token", "caller-token"]
