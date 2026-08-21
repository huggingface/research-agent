from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from research.archive_provisioning import ARCHIVE_TEMPLATE_VERSION
from research.okf_compiler import build_okf_files


def load_archive_module():
    path = Path(__file__).parents[1] / "deploy" / "research-archive" / "app.py"
    spec = importlib.util.spec_from_file_location("research_archive_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_okf_bundle(
    run: Path,
    report: str,
    *,
    brief_frontmatter: str = "",
) -> None:
    files, metadata = build_okf_files(
        report,
        title="Client Success Rates",
        description="Evidence-backed client success findings.",
        workspace_id=run.name,
        report_sha256=hashlib.sha256(report.encode()).hexdigest(),
        evidence_bytes=json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "hf-source",
                        "resource": "https://huggingface.co/",
                        "title": "Hugging Face",
                    }
                ],
            }
        ).encode(),
        generated_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    if brief_frontmatter:
        files["reports/brief.md"] = files["reports/brief.md"].replace(
            b"status: draft\n",
            f"status: draft\n{brief_frontmatter}".encode(),
            1,
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
            destination = run / "output" / "okf" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    bundle = output.getvalue()
    (run / "output" / "okf.zip").write_bytes(bundle)
    manifest = {
        "schema_version": 1,
        "stage": "knowledge",
        "status": "complete",
        "okf_version": "0.2",
        "source_report_sha256": metadata["report_sha256"],
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "warnings": metadata["warnings"],
        "artifacts": [
            {
                "path": f"output/okf/{path}",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in files.items()
        ]
        + [
            {
                "path": "output/okf.zip",
                "sha256": hashlib.sha256(bundle).hexdigest(),
            }
        ],
    }
    path = run / "scratch" / "knowledge" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))


def replace_okf_member(run: Path, member: str, content: bytes) -> None:
    destination = run / "output" / "okf" / member
    destination.write_bytes(content)
    bundle_path = run / "output" / "okf.zip"
    with zipfile.ZipFile(bundle_path) as archive:
        members = {
            name: archive.read(name)
            for name in archive.namelist()
        }
    members[member] = content
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    bundle = output.getvalue()
    bundle_path.write_bytes(bundle)
    manifest_path = run / "scratch" / "knowledge" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for artifact in manifest["artifacts"]:
        if artifact["path"] == f"output/okf/{member}":
            artifact["sha256"] = hashlib.sha256(content).hexdigest()
        elif artifact["path"] == "output/okf.zip":
            artifact["sha256"] = hashlib.sha256(bundle).hexdigest()
    manifest["bundle_sha256"] = hashlib.sha256(bundle).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_archive_indexes_reports_and_artifacts(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-07-22-client-success-rates-a123"
    report = (
        "# Client Success Rates\n\n"
        "[Source](https://huggingface.co/)[^hf-source]\n\n"
        "[^hf-source]: [Hugging Face](https://huggingface.co/)"
    )
    (run / "output" / "assets").mkdir(parents=True)
    (run / "scratch" / "research").mkdir(parents=True)
    (run / "output" / "report.md").write_text(report)
    (run / "output" / "report.html").write_text("<!doctype html><html></html>")
    (run / "output" / "assets" / "chart.svg").write_text("<svg></svg>")
    (run / "scratch" / "research" / "manifest.json").write_text(
        json.dumps({"stage": "research"})
    )
    (run / "scratch" / ".workspace.json").write_text(
        json.dumps({"checked_at": "2026-07-22T12:30:00+00:00"})
    )
    write_okf_bundle(run, report)

    archive = module.ResearchArchive(tmp_path)
    summaries = archive.list_runs()
    detail = archive.describe(run.name)
    files = archive.files(run.name)

    assert "rglob" not in module.ResearchArchive.summarize.__code__.co_names
    assert len(summaries) == 1
    assert summaries[0].status == "complete"
    assert summaries[0].title == "Client Success Rates"
    assert summaries[0].updated_at == "2026-07-22T12:30:00+00:00"
    assert summaries[0].asset_count is None
    assert summaries[0].trace_count is None
    assert detail["has_markdown"]
    assert detail["has_html"]
    assert detail["has_okf"]
    assert detail["markdown"] == report
    assert detail["research_manifest"] == {"stage": "research"}
    assert 'href="https://huggingface.co/"' in detail["markdown_html"]
    assert "files" not in detail
    assert any(file["path"] == "output/assets/chart.svg" for file in files)

    client = TestClient(module.create_app(tmp_path))
    response = client.get(f"/api/runs/{run.name}/files")
    assert response.status_code == 200
    assert response.json()["count"] == len(files)
    markdown = client.get(f"/api/runs/{run.name}/markdown")
    assert markdown.status_code == 200
    assert markdown.json()["markdown"] == detail["markdown"]
    evidence = client.get(f"/api/runs/{run.name}/evidence")
    assert evidence.status_code == 200
    payload = evidence.json()
    assert payload["valid"]
    assert payload["version"] == "0.2"
    assert payload["trust_tier"] == "unverified"
    assert payload["status"] == "draft"
    assert payload["integrity"]
    assert payload["report_integrity"]
    assert payload["source_count"] == 1
    assert payload["coverage_percent"] == 100
    assert payload["source_in_report_count"] == 1
    assert payload["formally_cited_source_count"] == 1
    assert payload["formal_claim_citation_count"] == 1
    assert payload["citation_coverage_percent"] == 100
    assert payload["sources"][0]["id"] == "hf-source"
    assert payload["sources"][0]["health"] == "healthy"
    download = client.get(payload["download_url"])
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")


def test_archive_separates_source_presence_from_formal_citations(
    tmp_path: Path,
) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-deterministic-timespot-vlm-97bb"
    (run / "output").mkdir(parents=True)
    sources = [
        {
            "id": f"timespot-source-{index}",
            "resource": f"https://example.test/source-{index}",
            "title": f"TimeSpot source {index}",
        }
        for index in range(1, 9)
    ]
    definitions = "\n".join(
        f"[^{source['id']}]: {source['resource']}" for source in sources
    )
    table = "\n".join(
        f"| {source['title']} | {source['resource']} |" for source in sources
    )
    report = (
        "# Deterministic TimeSpot VLM Reproduction\n\n"
        "## TL;DR\n\n"
        "TimeSpot can be reproduced deterministically with pinned model, "
        "dataset, adapter, and evaluation revisions.\n\n"
        "## Artifact registry\n\n"
        "| Artifact | URL |\n|---|---|\n"
        f"{table}\n\n"
        "Definitions alone are not claim citations.\n\n"
        f"{definitions}\n\n"
        "`A code token is not a citation.[^timespot-source-1]`\n\n"
        "| Navigation | [^timespot-source-2] |\n"
        "|---|---|\n\n"
        "Navigation | [^timespot-source-2]\n\n"
        "<!-- [^timespot-source-3] -->\n\n"
        "Text <span>Raw HTML.[^timespot-source-4]</span>\n\n"
        "<div>\nRaw HTML block.[^timespot-source-5]\n</div>\n"
    )
    (run / "output" / "report.md").write_text(report)
    files, metadata = build_okf_files(
        report,
        title="Deterministic TimeSpot VLM Reproduction",
        description="Research request: use https://example.test/raw/request",
        workspace_id=run.name,
        report_sha256=hashlib.sha256(report.encode()).hexdigest(),
        evidence_bytes=json.dumps(
            {"schema_version": 1, "sources": sources}
        ).encode(),
        generated_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
            destination = run / "output" / "okf" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    bundle = output.getvalue()
    (run / "output" / "okf.zip").write_bytes(bundle)
    manifest = {
        "schema_version": 1,
        "stage": "knowledge",
        "status": "complete",
        "okf_version": "0.2",
        "source_report_sha256": metadata["report_sha256"],
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "warnings": metadata["warnings"],
        "artifacts": [
            {
                "path": f"output/okf/{path}",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in files.items()
        ]
        + [
            {
                "path": "output/okf.zip",
                "sha256": hashlib.sha256(bundle).hexdigest(),
            }
        ],
    }
    manifest_path = run / "scratch" / "knowledge" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert payload["valid"]
    assert payload["description"] == (
        "TimeSpot can be reproduced deterministically with pinned model, "
        "dataset, adapter, and evaluation revisions."
    )
    assert payload["source_count"] == 8
    assert payload["source_in_report_count"] == 8
    assert payload["source_presence_percent"] == 100
    assert payload["report_link_count"] == 8
    assert payload["registered_report_link_count"] == 8
    assert payload["formal_claim_citation_count"] == 0
    assert payload["formally_cited_source_count"] == 0
    assert payload["citation_coverage_percent"] == 0
    assert all(source["in_report"] for source in payload["sources"])
    assert all(not source["cited"] for source in payload["sources"])
    assert [
        item["code"]
        for item in payload["diagnostics"]
        if item["code"] == "uncited-source"
    ] == ["uncited-source"]
    assert not any(
        item["code"] == "source-not-in-report"
        for item in payload["diagnostics"]
    )
    assert "8 source records have no formal claim footnote" in next(
        item["message"]
        for item in payload["diagnostics"]
        if item["code"] == "uncited-source"
    )


def test_archive_replaces_legacy_generic_source_title(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-21-generic-source-title-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Hugging Face](https://huggingface.co/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    brief_path = run / "output" / "okf" / "reports" / "brief.md"
    brief = brief_path.read_bytes().replace(
        b"title: Hugging Face",
        b"title: HTTPS",
        1,
    )
    replace_okf_member(run, "reports/brief.md", brief)

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert payload["valid"]
    assert payload["sources"][0]["title"] == "https://huggingface.co/"


def test_archive_reports_invalid_okf_without_rendering_untrusted_data(
    tmp_path: Path,
) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-invalid-okf-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    manifest_path = run / "scratch" / "knowledge" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))

    client = TestClient(module.create_app(tmp_path))
    payload = client.get(f"/api/runs/{run.name}/evidence").json()

    assert payload["available"]
    assert not payload["valid"]
    assert not payload["integrity"]
    assert any(
        item["code"] == "bundle-integrity"
        for item in payload["diagnostics"]
    )


def test_archive_derives_human_review_and_staleness(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-reviewed-okf-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(
        run,
        report,
        brief_frontmatter=(
            "verified: {by: 'human:alice', at: '2026-08-18T10:00:00Z'}\n"
            "stale_after: '2020-01-01'\n"
        ),
    )

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert payload["valid"]
    assert payload["trust_tier"] == "human-reviewed"
    assert payload["stale"]


def test_archive_detects_expanded_concept_tampering(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-tampered-okf-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    brief = run / "output" / "okf" / "reports" / "brief.md"
    brief.write_text(brief.read_text() + "\nTampered after release.\n")

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert not payload["valid"]
    assert not payload["integrity"]
    assert any(
        item["code"] == "artifact-integrity"
        for item in payload["diagnostics"]
    )


def test_archive_detects_expanded_evidence_register_tampering(
    tmp_path: Path,
) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-tampered-evidence-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    evidence = run / "output" / "okf" / "references" / "evidence.md"
    evidence.write_text(evidence.read_text() + "\nTampered evidence register.\n")

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert not payload["valid"]
    assert not payload["integrity"]
    assert any(
        item["code"] == "artifact-integrity"
        for item in payload["diagnostics"]
    )


def test_archive_rejects_zip_that_differs_from_expanded_concepts(
    tmp_path: Path,
) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-zip-mismatch-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    bundle_path = run / "output" / "okf.zip"
    with zipfile.ZipFile(bundle_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["reports/brief.md"] += b"\nDifferent downloadable content.\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    bundle = output.getvalue()
    bundle_path.write_bytes(bundle)
    manifest_path = run / "scratch" / "knowledge" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle_sha256"] = hashlib.sha256(bundle).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["path"] == "output/okf.zip":
            artifact["sha256"] = manifest["bundle_sha256"]
    manifest_path.write_text(json.dumps(manifest))

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert not payload["valid"]
    assert not payload["archive_integrity"]
    assert any(
        item["code"] == "archive-contents"
        for item in payload["diagnostics"]
    )


def test_archive_returns_diagnostics_for_partial_okf_release(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-partial-okf-a123"
    (run / "output").mkdir(parents=True)
    (run / "output" / "report.md").write_text("# Report")
    manifest = run / "scratch" / "knowledge" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"stage": "knowledge"}')

    client = TestClient(module.create_app(tmp_path))
    summary = client.get("/api/runs").json()["runs"][0]
    payload = client.get(f"/api/runs/{run.name}/evidence").json()

    assert summary["has_okf"]
    assert payload["available"]
    assert not payload["valid"]
    assert payload["diagnostics"][0]["code"] == "incomplete-bundle"


def test_archive_rejects_unknown_lifecycle_status(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-status-okf-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    brief = run / "output" / "okf" / "reports" / "brief.md"
    content = brief.read_bytes().replace(b"status: draft", b"status: invented", 1)
    replace_okf_member(run, "reports/brief.md", content)

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert not payload["valid"]
    assert any(
        item["code"] == "invalid-status"
        for item in payload["diagnostics"]
    )


def test_archive_rejects_encoded_sensitive_source_query(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-08-19-sensitive-source-a123"
    (run / "output").mkdir(parents=True)
    report = "# Report\n\n[Source](https://example.test/)"
    (run / "output" / "report.md").write_text(report)
    write_okf_bundle(run, report)
    brief = run / "output" / "okf" / "reports" / "brief.md"
    content = brief.read_bytes().replace(
        b"https://example.test/",
        b"https://example.test/?%74oken=secret",
    )
    replace_okf_member(run, "reports/brief.md", content)

    payload = TestClient(module.create_app(tmp_path)).get(
        f"/api/runs/{run.name}/evidence"
    ).json()

    assert not payload["valid"]
    assert any(
        item["code"] == "invalid-source-url"
        for item in payload["diagnostics"]
    )


def test_archive_renders_same_run_markdown_images(tmp_path: Path) -> None:
    module = load_archive_module()
    run_id = "26-07-29-trending-model-survey-ba08"
    run = tmp_path / run_id
    image = run / "scratch" / "research" / "chart.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    (run / "output").mkdir()
    (run / "output" / "report.md").write_text(
        "# Report\n\n"
        "![Chart](https://huggingface.co/buckets/evalstate/research-agent/"
        f"resolve/{run_id}/scratch/research/chart.png)"
    )
    archive = module.ResearchArchive(
        tmp_path,
        bucket_id="evalstate/research-agent",
    )

    detail = archive.describe(run_id)

    assert (
        f'<img alt="Chart" src="/files/{run_id}/scratch/research/chart.png">'
        in detail["markdown_html"]
    )


def test_archive_rejects_untrusted_markdown_images(tmp_path: Path) -> None:
    module = load_archive_module()
    run_id = "26-07-29-private-a123"
    run = tmp_path / run_id
    (run / "output").mkdir(parents=True)
    (run / "output" / "report.md").write_text(
        "# Report\n\n"
        "![External](https://example.com/chart.png)\n\n"
        '<img src="/files/other-run/output/chart.png" onerror="alert(1)">'
    )
    archive = module.ResearchArchive(
        tmp_path,
        bucket_id="evalstate/research-agent",
    )

    html = archive.describe(run_id)["markdown_html"]

    assert "Image unavailable: External" in html
    assert "<img" not in html
    assert "onerror" not in html


def test_archive_renders_display_math_without_scripts() -> None:
    module = load_archive_module()

    html = module.render_markdown(
        r"Before\n\n$$\left(V_n^\ell,L_n^\ell\right)$$\n\nAfter"
    )

    assert "<math" in html
    assert 'display="block"' in html
    assert "$$" not in html
    assert "<script" not in html


def test_archive_math_cannot_emit_active_links_or_markup() -> None:
    module = load_archive_module()

    html = module.render_markdown(
        r"$$\href{javascript:alert(1)}{click}$$"
        "\n\n"
        r"$$\text{</math><script>alert(1)</script>}$$"
    )

    assert "javascript:" not in html
    assert "href=" not in html
    assert "<script" not in html


def test_archive_rejects_paths_outside_a_run(tmp_path: Path) -> None:
    module = load_archive_module()
    archive = module.ResearchArchive(tmp_path)

    for value in ("../secret", "/etc/passwd", "run/../../secret"):
        try:
            archive.file_path("valid-run", value)
        except (FileNotFoundError, ValueError):
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {value}")


def test_archive_rejects_symlinked_runs_and_assets(tmp_path: Path) -> None:
    module = load_archive_module()
    outside = tmp_path / "_outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"secret")
    run_id = "26-07-29-symlink-a123"
    (tmp_path / run_id).symlink_to(outside, target_is_directory=True)
    archive = module.ResearchArchive(tmp_path)

    assert not archive.list_runs()
    for operation in (
        lambda: archive.describe(run_id),
        lambda: archive.files(run_id),
        lambda: archive.file_path(run_id, "secret.png"),
    ):
        try:
            operation()
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("symlinked run was accepted")

    safe_run = tmp_path / "26-07-29-safe-b456"
    (safe_run / "output").mkdir(parents=True)
    (safe_run / "output" / "linked.png").symlink_to(outside / "secret.png")
    try:
        archive.file_path(safe_run.name, "output/linked.png")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("symlinked artifact was accepted")
    assert archive.files(safe_run.name) == []


def test_archive_rejects_symlinked_canonical_files(tmp_path: Path) -> None:
    module = load_archive_module()
    outside = tmp_path / "_outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("# Secret\n\nDo not disclose")
    manifest = outside / "manifest.json"
    manifest.write_text('{"secret": true}')
    run = tmp_path / "26-07-30-safe-a123"
    (run / "output").mkdir(parents=True)
    (run / "scratch" / "research").mkdir(parents=True)
    (run / "output" / "report.md").symlink_to(secret)
    (run / "scratch" / "research" / "manifest.json").symlink_to(manifest)
    archive = module.ResearchArchive(tmp_path)

    summary = archive.list_runs()[0]
    detail = archive.describe(run.name)

    assert summary.has_markdown is False
    assert summary.title == "Safe"
    assert detail["markdown"] == ""
    assert detail["research_manifest"] is None
    assert archive.files(run.name) == []


def test_markerless_run_uses_direct_report_timestamp(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "legacy-run"
    report = run / "output" / "report.md"
    artifact = run / "scratch" / "research" / "later.txt"
    report.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    report.write_text("# Legacy")
    artifact.write_text("later")
    report_time = datetime(2026, 7, 20, 12, tzinfo=UTC).timestamp()
    os.utime(run, (report_time - 10, report_time - 10))
    os.utime(report, (report_time, report_time))
    os.utime(artifact, (report_time + 100, report_time + 100))

    summary = module.ResearchArchive(tmp_path).list_runs()[0]

    assert summary.updated_at == "2026-07-20T12:00:00+00:00"


def test_archive_deletes_only_a_valid_run(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-07-22-delete-me-a123"
    sibling = tmp_path / "26-07-22-keep-me-b456"
    (run / "output").mkdir(parents=True)
    (run / "output" / "report.md").write_text("# Delete Me")
    sibling.mkdir()
    archive = module.ResearchArchive(tmp_path)

    archive.delete(run.name)

    assert not run.exists()
    assert sibling.is_dir()
    for invalid in ("../keep-me", ".", "/research"):
        try:
            archive.delete(invalid)
        except (FileNotFoundError, ValueError):
            pass
        else:
            raise AssertionError(f"unsafe run id accepted: {invalid}")


def test_delete_endpoint_removes_run_and_returns_404_afterward(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-07-22-delete-me-a123"
    (run / "output").mkdir(parents=True)
    (run / "output" / "report.md").write_text("# Delete Me")
    client = TestClient(module.create_app(tmp_path))

    response = client.delete(f"/api/runs/{run.name}")

    assert response.status_code == 200
    assert response.json() == {"deleted": run.name}
    assert client.get(f"/api/runs/{run.name}").status_code == 404
    assert client.delete(f"/api/runs/{run.name}").status_code == 404


def test_read_only_archive_hides_delete_and_rejects_endpoint(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-07-22-keep-me-a123"
    (run / "output").mkdir(parents=True)
    (run / "output" / "report.md").write_text("# Keep Me")
    client = TestClient(module.create_app(tmp_path, read_only=True))

    assert client.get("/api/config").json() == {"read_only": True}
    response = client.delete(f"/api/runs/{run.name}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Archive is read-only"}
    assert run.is_dir()
    assert client.get("/health").json()["read_only"] is True


def test_artifact_download_uses_attachment_disposition(tmp_path: Path) -> None:
    module = load_archive_module()
    report = tmp_path / "26-07-22-download-a123" / "output" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text(
        "<!doctype html><style>body{color:green}</style>"
        "<script>fetch('/api/runs')</script>"
        "<img src=x onerror=alert(1)>"
    )
    client = TestClient(module.create_app(tmp_path))
    url = "/files/26-07-22-download-a123/output/report.html"

    inline = client.get(url)
    download = client.get(f"{url}?download=true")

    assert inline.headers["content-disposition"] == 'inline; filename="report.html"'
    assert download.headers["content-disposition"] == (
        'attachment; filename="report.html"'
    )
    assert inline.headers["cache-control"] == "private, max-age=300"
    assert inline.headers["x-content-type-options"] == "nosniff"
    assert inline.headers["referrer-policy"] == "no-referrer"
    assert inline.headers["content-security-policy"] == module.ARTIFACT_CSP
    assert download.headers["content-security-policy"] == module.ARTIFACT_CSP
    for directive in (
        "script-src 'none'",
        "connect-src 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
        "sandbox allow-popups allow-popups-to-escape-sandbox",
    ):
        assert directive in module.ARTIFACT_CSP
    assert "frame-ancestors" not in module.ARTIFACT_CSP


def test_svg_artifact_is_restricted_when_opened_directly(tmp_path: Path) -> None:
    module = load_archive_module()
    image = tmp_path / "26-07-22-svg-a123" / "output" / "assets" / "chart.svg"
    image.parent.mkdir(parents=True)
    image.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        "<script>alert(1)</script></svg>"
    )
    client = TestClient(module.create_app(tmp_path))

    response = client.get("/files/26-07-22-svg-a123/output/assets/chart.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["content-security-policy"] == module.ARTIFACT_CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_archive_serves_hub_classic_shell_and_logo(tmp_path: Path) -> None:
    module = load_archive_module()
    client = TestClient(module.create_app(tmp_path))

    page = client.get("/")
    logo = client.get("/assets/huggingface-logo.svg")

    assert page.status_code == 200
    assert "Hugging Face" in page.text
    assert "Research Archive" in page.text
    assert "research-archive-theme" in page.text
    assert "fonts.googleapis.com" in page.text
    assert "<h2>${escapeHtml(run.title)}</h2>" not in page.text
    assert 'class="detail-toolbar"' in page.text
    assert "html-panel" in page.text
    assert 'summary.has_html ? "html"' in page.text
    assert "Copy Markdown" in page.text
    assert "navigator.clipboard" in page.text
    assert "Open in new window ↗" in page.text
    assert "Open full report" not in page.text
    assert 'target="_blank" rel="noopener noreferrer"' in page.text
    assert "markdowns: new Map()" in page.text
    assert "inventories: new Map()" in page.text
    assert "evidences: new Map()" in page.text
    assert '...(run.has_okf ? ["evidence"] : [])' in page.text
    assert 'fetch(`/api/runs/${encodeURIComponent(id)}/evidence`)' in page.text
    assert "Download OKF bundle" in page.text
    assert "All provenance checks" in page.text
    assert "Bundle integrity" in page.text
    assert "Source records" in page.text
    assert "In report" in page.text
    assert "Claim-cited" in page.text
    assert "Link coverage" not in page.text
    assert '<details class="diagnostics"' in page.text
    assert 'document.title = "Research Archive"' in page.text
    assert 'fileUrl(id, "output/report.html")' in page.text
    assert 'fetch(`/api/runs/${encodeURIComponent(id)}/markdown`)' in page.text
    assert 'fetch(`/api/runs/${encodeURIComponent(id)}/files`)' in page.text
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/svg+xml")
    assert client.get("/health").json()["template_version"] == ARCHIVE_TEMPLATE_VERSION
    assert module.TEMPLATE_MARKER["template_version"] == ARCHIVE_TEMPLATE_VERSION
