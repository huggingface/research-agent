from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from research.archive_provisioning import ARCHIVE_TEMPLATE_VERSION


def load_archive_module():
    path = Path(__file__).parents[1] / "deploy" / "research-archive" / "app.py"
    spec = importlib.util.spec_from_file_location("research_archive_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_archive_indexes_reports_and_artifacts(tmp_path: Path) -> None:
    module = load_archive_module()
    run = tmp_path / "26-07-22-client-success-rates-a123"
    (run / "output" / "assets").mkdir(parents=True)
    (run / "scratch" / "research").mkdir(parents=True)
    (run / "output" / "report.md").write_text(
        "# Client Success Rates\n\n[Source](https://huggingface.co/)"
    )
    (run / "output" / "report.html").write_text("<!doctype html><html></html>")
    (run / "output" / "assets" / "chart.svg").write_text("<svg></svg>")
    (run / "scratch" / "research" / "manifest.json").write_text(
        json.dumps({"stage": "research"})
    )
    (run / "scratch" / ".workspace.json").write_text(
        json.dumps({"checked_at": "2026-07-22T12:30:00+00:00"})
    )

    archive = module.ResearchArchive(tmp_path)
    summaries = archive.list_runs()
    detail = archive.describe(run.name)

    assert len(summaries) == 1
    assert summaries[0].status == "complete"
    assert summaries[0].title == "Client Success Rates"
    assert summaries[0].updated_at == "2026-07-22T12:30:00+00:00"
    assert detail["has_markdown"]
    assert detail["has_html"]
    assert detail["markdown"] == (
        "# Client Success Rates\n\n[Source](https://huggingface.co/)"
    )
    assert detail["research_manifest"] == {"stage": "research"}
    assert 'href="https://huggingface.co/"' in detail["markdown_html"]
    assert any(file["path"] == "output/assets/chart.svg" for file in detail["files"])


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
    assert 'state.detail.has_html ? "html"' in page.text
    assert "Copy Markdown" in page.text
    assert "navigator.clipboard" in page.text
    assert "Open in new window ↗" in page.text
    assert "Open full report" not in page.text
    assert 'target="_blank" rel="noopener noreferrer"' in page.text
    assert "details: new Map()" in page.text
    assert "state.details.get(id)" in page.text
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/svg+xml")
    assert client.get("/health").json()["template_version"] == "1.2.5"
    assert module.TEMPLATE_MARKER["template_version"] == ARCHIVE_TEMPLATE_VERSION
