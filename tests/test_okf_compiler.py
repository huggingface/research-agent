from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from fast_agent import AgentAuth

from research.app_jobs import ResearchJob
from research.okf_compiler import (
    KNOWLEDGE_MANIFEST,
    build_okf_files,
    compile_okf_bundle,
)


class BucketSimulator:
    def __init__(self, report: bytes, evidence: bytes | None = None) -> None:
        self.report = report
        self.evidence = evidence
        self.uploads: list[list[tuple[bytes, str]]] = []

    def whoami(self, *, token: str) -> dict[str, str]:
        assert token == "caller-token"
        return {"name": "alice"}

    def list_bucket_tree(self, bucket_id: str, **_: Any):
        assert bucket_id == "alice/research-agent"
        files = [
            SimpleNamespace(
                type="file",
                path="run-123/output/report.md",
                size=len(self.report),
            )
        ]
        if self.evidence is not None:
            files.append(
                SimpleNamespace(
                    type="file",
                    path="run-123/scratch/research/evidence.json",
                    size=len(self.evidence),
                )
            )
        return files

    def download_bucket_files(
        self,
        bucket_id: str,
        downloads: list[tuple[str, Path]],
        **_: Any,
    ) -> None:
        assert bucket_id == "alice/research-agent"
        for remote, local in downloads:
            local.write_bytes(
                self.evidence
                if remote.endswith("evidence.json")
                else self.report
            )

    def batch_bucket_files(
        self,
        bucket_id: str,
        *,
        add: list[tuple[bytes, str]],
        token: str,
    ) -> None:
        assert bucket_id == "alice/research-agent"
        assert token == "caller-token"
        self.uploads.append(add)


def frontmatter(content: bytes) -> dict[str, Any]:
    _, raw, _ = content.decode().split("---", 2)
    value = yaml.safe_load(raw)
    assert isinstance(value, dict)
    return value


def test_builds_conformant_bundle_with_stable_citations() -> None:
    report = (
        "# MCP Findings\n\n"
        "The [official docs](https://EXAMPLE.test:443/docs#oauth) describe OAuth.\n\n"
        "Repeated [documentation](https://example.test/docs) agrees.\n\n"
        "`[code link](https://ignore.test/)`\n\n"
        "```\n[also code](https://ignore.test/)\n```\n"
    )
    evidence = json.dumps(
        {
            "schema_version": 1,
            "sources": [
                {
                    "id": "official-docs",
                    "resource": "https://example.test/docs",
                    "title": "Official documentation",
                    "author": "team:docs",
                    "last_modified": "2026-08-01",
                }
            ],
        }
    ).encode()

    files, metadata = build_okf_files(
        report,
        title="Fallback title",
        description="A focused test",
        workspace_id="run-123",
        report_sha256="abc123",
        evidence_bytes=evidence,
        generated_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )

    assert set(files) == {
        "index.md",
        "reports/index.md",
        "reports/brief.md",
        "references/index.md",
        "references/evidence.md",
    }
    brief = files["reports/brief.md"].decode()
    fm = frontmatter(files["reports/brief.md"])
    assert fm["type"] == "Research Report"
    assert fm["status"] == "draft"
    assert "verified" not in fm
    assert fm["generated"]["by"] == "research-agent/okf-compiler-v1"
    assert fm["sources"] == [
        {
            "id": "official-docs",
            "resource": "https://example.test/docs",
            "title": "Official documentation",
            "author": "team:docs",
            "last_modified": "2026-08-01",
        }
    ]
    assert brief.count("[^official-docs]") == 3
    assert "ignore.test" not in str(fm)
    assert metadata["source_count"] == 1
    assert metadata["citation_count"] == 1
    assert files["index.md"].startswith(b'---\nokf_version: "0.2"')


def test_falls_back_to_external_links_when_evidence_is_invalid() -> None:
    report = "# Report\n\nSee [source](https://example.test/a#section).\n"

    files, metadata = build_okf_files(
        report,
        title="Report",
        description="Description",
        workspace_id="run",
        report_sha256="digest",
        evidence_bytes=b"{not-json",
    )

    sources = frontmatter(files["reports/brief.md"])["sources"]
    assert len(sources) == 1
    assert sources[0]["resource"] == "https://example.test/a"
    assert sources[0]["id"].startswith("src-")
    assert any("invalid JSON" in warning for warning in metadata["warnings"])


def test_preserves_existing_stable_source_footnotes() -> None:
    report = (
        "# Report\n\n"
        "The API supports this operation.[^api-docs]\n\n"
        "[^api-docs]: [API documentation](https://example.test/api)\n"
    )

    files, metadata = build_okf_files(
        report,
        title="Report",
        description="Description",
        workspace_id="run",
        report_sha256="digest",
    )

    sources = frontmatter(files["reports/brief.md"])["sources"]
    assert sources == [
        {
            "id": "api-docs",
            "resource": "https://example.test/api",
            "title": "API documentation",
        }
    ]
    assert metadata["citation_count"] == 1
    assert not any("not cited" in warning for warning in metadata["warnings"])


def test_reordering_links_does_not_change_generated_source_ids() -> None:
    kwargs = {
        "title": "Report",
        "description": "Description",
        "workspace_id": "run",
        "report_sha256": "digest",
    }
    first, _ = build_okf_files(
        "# R\n\n[A](https://a.test/)\n[B](https://b.test/)\n",
        **kwargs,
    )
    second, _ = build_okf_files(
        "# R\n\n[B](https://b.test/)\n[A](https://a.test/)\n",
        **kwargs,
    )

    first_sources = frontmatter(first["reports/brief.md"])["sources"]
    second_sources = frontmatter(second["reports/brief.md"])["sources"]
    assert first_sources == second_sources


def test_publishes_bundle_then_completion_manifest() -> None:
    report = b"# Report\n\n[Source](https://example.test/docs)\n"
    evidence = json.dumps({"schema_version": 1, "sources": []}).encode()
    api = BucketSimulator(report, evidence)
    job = ResearchJob(
        id="job",
        topic="Topic",
        owner_id="alice",
        headline="Report",
        workspace_id="run-123",
    )

    result = compile_okf_bundle(
        job,
        AgentAuth.bearer("caller-token"),
        api=api,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 8, 19, 12, tzinfo=UTC),
    )

    assert len(api.uploads) == 2
    bundle_paths = {path for _, path in api.uploads[0]}
    assert "run-123/output/okf/reports/brief.md" in bundle_paths
    assert "run-123/output/okf.zip" in bundle_paths
    assert api.uploads[1][0][1] == f"run-123/{KNOWLEDGE_MANIFEST}"
    manifest = json.loads(api.uploads[1][0][0])
    assert manifest["stage"] == "knowledge"
    assert manifest["status"] == "complete"
    assert manifest["bundle_sha256"] == result.bundle_sha256
    assert manifest["source_report_sha256"] == hashlib.sha256(report).hexdigest()
    archive_bytes = next(
        content
        for content, path in api.uploads[0]
        if path.endswith("output/okf.zip")
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert "index.md" in archive.namelist()
        assert "reports/brief.md" in archive.namelist()
    assert result.source_count == 1
    assert result.bundle_url.endswith("/run-123/output/okf.zip?download=true")


def test_does_not_treat_sensitive_or_credentialed_urls_as_sources() -> None:
    report = (
        "# Report\n\n"
        "[Token](https://example.test/?token=secret)\n"
        "[Encoded token](https://example.test/?%74oken=secret)\n"
        "[Semicolon token](https://example.test/?safe=1;token=secret)\n"
        "[Encoded separator](https://example.test/?safe=1%3Btoken=secret)\n"
        "[Credentials](https://user:pass@example.test/private)\n"
        "[Bad port](https://example.test:bad/private)\n"
        "[Safe](https://example.test/public)\n"
    )

    files, _ = build_okf_files(
        report,
        title="Report",
        description="Description",
        workspace_id="run",
        report_sha256="digest",
    )

    sources = frontmatter(files["reports/brief.md"])["sources"]
    assert [source["resource"] for source in sources] == [
        "https://example.test/public"
    ]
    assert "secret" not in files["references/evidence.md"].decode()
