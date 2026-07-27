from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest


def load_module():
    path = Path(__file__).parents[1] / "scripts" / "publish_reports.py"
    spec = importlib.util.spec_from_file_location("publish_reports", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FileSystemSimulator:
    def __init__(self, files: dict[str, bytes]):
        self.files = files

    def find(self, root: str, detail: bool = False):
        assert detail
        return {
            path: {"type": "file", "size": len(value)}
            for path, value in self.files.items()
            if path.startswith(f"{root}/")
        }

    def info(self, path: str):
        if path not in self.files:
            raise FileNotFoundError(path)
        return {"type": "file", "size": len(self.files[path])}

    def open(self, path: str, mode: str):
        if mode == "rb":
            if path not in self.files:
                raise FileNotFoundError(path)
            return io.BytesIO(self.files[path])
        assert mode == "wb"
        return WritableBytes(self.files, path)


class WritableBytes(io.BytesIO):
    def __init__(self, files: dict[str, bytes], path: str):
        super().__init__()
        self.files = files
        self.path = path

    def close(self) -> None:
        self.files[self.path] = self.getvalue()
        super().close()


def test_discovery_allows_only_public_report_artifacts() -> None:
    module = load_module()
    root = "buckets/evalstate/research-agent/run-a/output"
    fs = FileSystemSimulator(
        {
            f"{root}/report.md": b"# Report",
            f"{root}/report.html": b"<html>",
            f"{root}/assets/chart.png": b"png",
            f"{root}/chart.svg": b"svg",
            f"{root}/summary.json": b'{"private": true}',
            f"{root}/analysis.py": b"secret",
            "buckets/evalstate/research-agent/run-a/scratch/research/notes.md": (
                b"private"
            ),
        }
    )

    artifacts = module.discover_artifacts(fs, "evalstate/research-agent", ["run-a"])

    assert {item.relative_path for item in artifacts} == {
        "output/report.md",
        "output/report.html",
        "output/assets/chart.png",
        "output/chart.svg",
    }


def test_discovery_requires_both_reports() -> None:
    module = load_module()
    fs = FileSystemSimulator(
        {
            "buckets/evalstate/research-agent/run-a/output/report.md": b"# Report",
        }
    )

    with pytest.raises(module.PublicationError, match="missing report"):
        module.discover_artifacts(fs, "evalstate/research-agent", ["run-a"])


def test_copy_is_idempotent_and_never_changes_source() -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    destination = "buckets/evalstate/public/run-a/output/report.md"
    fs = FileSystemSimulator({source: b"# Report"})
    artifact = module.Artifact("run-a", "output/report.md", source, 8)
    content = module.public_bytes(
        fs, artifact, "evalstate/research-agent", "evalstate/public"
    )

    assert module.artifact_changed(fs, content, destination)
    module.copy_artifact(fs, content, destination)

    assert not module.artifact_changed(fs, content, destination)
    assert fs.files[source] == b"# Report"
    assert fs.files[destination] == b"# Report"


def test_publication_rewrites_private_bucket_links() -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator(
        {
            source: (
                b"https://huggingface.co/buckets/evalstate/research-agent/"
                b"tree/run-a/output/report.md"
            )
        }
    )
    artifact = module.Artifact("run-a", "output/report.md", source, 100)

    content = module.public_bytes(
        fs, artifact, "evalstate/research-agent", "evalstate/public"
    )

    assert b"evalstate/research-agent" not in content
    assert b"huggingface.co/buckets/evalstate/public/tree/run-a" in content


def test_publication_rejects_tokens() -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator({source: b"hf_abcdefghijklmnopqrstuvwxyz"})
    artifact = module.Artifact("run-a", "output/report.md", source, 29)

    with pytest.raises(module.PublicationError, match="token"):
        module.public_bytes(
            fs, artifact, "evalstate/research-agent", "evalstate/public"
        )


def test_cli_requires_explicit_run_selection() -> None:
    module = load_module()

    with pytest.raises(SystemExit):
        module.parser().parse_args([])
