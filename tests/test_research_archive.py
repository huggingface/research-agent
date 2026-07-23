from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


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
    assert detail["research_manifest"] == {"stage": "research"}
    assert "href=\"https://huggingface.co/\"" in detail["markdown_html"]
    assert any(file["path"] == "output/assets/chart.svg" for file in detail["files"])


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


def test_artifact_download_uses_attachment_disposition(tmp_path: Path) -> None:
    module = load_archive_module()
    report = tmp_path / "26-07-22-download-a123" / "output" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<!doctype html><title>Download</title>")
    client = TestClient(module.create_app(tmp_path))
    url = "/files/26-07-22-download-a123/output/report.html"

    inline = client.get(url)
    download = client.get(f"{url}?download=true")

    assert inline.headers["content-disposition"] == 'inline; filename="report.html"'
    assert download.headers["content-disposition"] == (
        'attachment; filename="report.html"'
    )


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
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/svg+xml")
