from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest


def load_module():
    path = Path(__file__).parents[1] / "scripts" / "publish_reports.py"
    spec = importlib.util.spec_from_file_location("publish_reports", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_okf_archive():
    path = Path(__file__).parents[1] / "deploy" / "research-archive" / "okf_archive.py"
    spec = importlib.util.spec_from_file_location("public_okf_archive", path)
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


class BatchApiSimulator:
    def __init__(self):
        self.calls = []

    def batch_bucket_files(self, bucket_id, **kwargs):
        self.calls.append((bucket_id, kwargs))


class ApplyingBatchApiSimulator(BatchApiSimulator):
    def __init__(self, fs: FileSystemSimulator):
        super().__init__()
        self.fs = fs

    def batch_bucket_files(self, bucket_id, **kwargs):
        super().batch_bucket_files(bucket_id, **kwargs)
        root = f"buckets/{bucket_id}"
        for path in kwargs.get("delete", []):
            self.fs.files.pop(f"{root}/{path}", None)
        for content, path in kwargs.get("add", []):
            self.fs.files[f"{root}/{path}"] = content


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
            f"{root}/okf.zip": b"private knowledge",
            f"{root}/okf/index.md": b"private index",
            f"{root}/okf/chart.png": b"private evidence",
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
    assert not module.is_public_artifact("output/okf.zip")
    assert not module.is_public_artifact("output/okf/index.md")
    assert not module.is_public_artifact("output/okf/chart.png")


def test_discovery_requires_both_reports() -> None:
    module = load_module()
    fs = FileSystemSimulator(
        {
            "buckets/evalstate/research-agent/run-a/output/report.md": b"# Report",
        }
    )

    with pytest.raises(module.PublicationError, match="missing report"):
        module.discover_artifacts(fs, "evalstate/research-agent", ["run-a"])


def test_comparison_is_idempotent_and_never_changes_source() -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    destination = "buckets/evalstate/public/run-a/output/report.md"
    fs = FileSystemSimulator({source: b"# Report"})
    artifact = module.Artifact("run-a", "output/report.md", source, 8)
    content = module.public_bytes(
        fs, artifact, "evalstate/research-agent", "evalstate/public"
    )

    assert module.artifact_changed(fs, content, destination)
    fs.files[destination] = content

    assert not module.artifact_changed(fs, content, destination)
    assert fs.files[source] == b"# Report"
    assert fs.files[destination] == b"# Report"


def test_upload_batches_all_changed_files() -> None:
    module = load_module()
    api = BatchApiSimulator()
    additions = [(b"one", "run-a/output/report.md"), (b"two", "run-b/report.md")]

    module.batch_upload(api, "evalstate/public", additions, "token")

    assert api.calls == [
        (
            "evalstate/public",
            {"add": additions, "token": "token"},
        )
    ]


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


@pytest.mark.parametrize(
    "value, message",
    [
        (
            (
                "https://huggingface.co/buckets/evalstate%2Fresearch-agent/"
                "resolve/run-a/scratch/research/evidence.json"
            ),
            "private source bucket",
        ),
        ("https://user:pass@example.test/private", "URL credentials"),
        ("https://example.test/private?token=secret", "sensitive URL query"),
        ("https://example.test/private?%74oken=secret", "sensitive URL query"),
    ],
)
def test_publication_rejects_encoded_private_or_credentialed_urls(
    value: str,
    message: str,
) -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator({source: f"[Private]({value})".encode()})
    artifact = module.Artifact("run-a", "output/report.md", source, len(fs.files[source]))

    with pytest.raises(module.PublicationError, match=message):
        module.public_bytes(
            fs,
            artifact,
            "evalstate/research-agent",
            "evalstate/public",
        )


@pytest.mark.parametrize(
    "path, value, message",
    [
        (
            "output/assets/chart.svg",
            (
                "<svg><a href=\"https://huggingface.co/buckets/"
                "evalstate%2Fresearch-agent/private\"></a></svg>"
            ),
            "private source bucket",
        ),
        (
            "output/site.css",
            "body{background:url(https://example.test/a?token=secret)}",
            "sensitive URL query",
        ),
        (
            "output/site.css",
            (
                "body{background:url(https://huggingface.co/buckets/"
                "evalstate\\2fresearch-agent/private.png)}"
            ),
            "private source bucket",
        ),
        (
            "output/site.css",
            "body{background:url(https://example.test/a?to\\00006ben=secret)}",
            "sensitive URL query",
        ),
        (
            "output/assets/chart.svg",
            "<svg><text>hf&#95;abcdefghijklmnopqrstuvwxyz</text></svg>",
            "Hugging Face token",
        ),
    ],
)
def test_publication_rejects_private_urls_in_text_media(
    path: str,
    value: str,
    message: str,
) -> None:
    module = load_module()
    source = f"buckets/evalstate/research-agent/run-a/{path}"
    fs = FileSystemSimulator({source: value.encode()})
    artifact = module.Artifact("run-a", path, source, len(fs.files[source]))

    with pytest.raises(module.PublicationError, match=message):
        module.public_bytes(
            fs,
            artifact,
            "evalstate/research-agent",
            "evalstate/public",
        )


def test_publication_rejects_deeply_encoded_private_bucket() -> None:
    module = load_module()
    value = (
        "https://huggingface.co/buckets/evalstate/research-agent/"
        "resolve/run-a/private"
    )
    for _ in range(12):
        value = quote(value, safe="")
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator({source: value.encode()})
    artifact = module.Artifact("run-a", "output/report.md", source, len(fs.files[source]))

    with pytest.raises(module.PublicationError, match="private source bucket"):
        module.public_bytes(
            fs,
            artifact,
            "evalstate/research-agent",
            "evalstate/public",
        )


def test_publication_rejects_private_okf_links() -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator(
        {
            source: (
                b"[Evidence](https://huggingface.co/buckets/"
                b"evalstate/research-agent/resolve/run-a/output/okf.zip)"
            )
        }
    )
    artifact = module.Artifact("run-a", "output/report.md", source, 100)

    with pytest.raises(module.PublicationError, match="private OKF"):
        module.public_bytes(
            fs,
            artifact,
            "evalstate/research-agent",
            "evalstate/public",
        )


@pytest.mark.parametrize(
    "path",
    [
        "output/%6f%6bf.zip",
        "output//okf//index.md",
        "output/%256f%256bf.zip",
        "output/%2525256f%2525256bf.zip",
    ],
)
def test_publication_rejects_encoded_private_okf_links(path: str) -> None:
    module = load_module()
    source = "buckets/evalstate/research-agent/run-a/output/report.md"
    fs = FileSystemSimulator(
        {
            source: (
                f"[Evidence](https://huggingface.co/buckets/evalstate/public/"
                f"resolve/run-a/{path})"
            ).encode()
        }
    )
    artifact = module.Artifact("run-a", "output/report.md", source, 100)

    with pytest.raises(module.PublicationError, match="private OKF"):
        module.public_bytes(
            fs,
            artifact,
            "evalstate/research-agent",
            "evalstate/public",
        )


def test_public_evidence_is_deterministic_safe_and_archive_compatible() -> None:
    module = load_module()
    report = (
        b"# Public Report\n\n"
        b"A supported claim.[^docs]\n\n"
        b"[^docs]: [HTTPS](https://example.test/docs)\n"
    )
    prepared = [
        ("run-a", "output/report.md", report),
        ("run-a", "output/report.html", b"<html></html>"),
    ]

    first = module.prepare_public_evidence(
        prepared,
        "evalstate/research-agent",
    )
    second = module.prepare_public_evidence(
        prepared,
        "evalstate/research-agent",
    )

    assert first == second
    release = {path: content for _, path, content in first}
    assert set(release) == {
        "output/okf/index.md",
        "output/okf/reports/index.md",
        "output/okf/reports/brief.md",
        "output/okf/references/index.md",
        "output/okf/references/evidence.md",
        "output/okf.zip",
        "scratch/knowledge/manifest.json",
    }
    manifest = json.loads(release["scratch/knowledge/manifest.json"])
    assert manifest["generated"] == {
        "by": "research-agent/public-okf-compiler-v1"
    }
    assert manifest["source_report_sha256"] == hashlib.sha256(report).hexdigest()
    assert b"evalstate/research-agent" not in b"".join(release.values())
    with zipfile.ZipFile(io.BytesIO(release["output/okf.zip"])) as archive:
        assert set(archive.namelist()) == {
            path.removeprefix("output/okf/")
            for path in release
            if path.startswith("output/okf/")
        }

    projection = load_okf_archive().inspect_okf(
        index=release["output/okf/index.md"],
        brief=release["output/okf/reports/brief.md"],
        manifest=release["scratch/knowledge/manifest.json"],
        bundle=release["output/okf.zip"],
        report=report.decode(),
        expanded={
            "reports/index.md": release["output/okf/reports/index.md"],
            "references/index.md": release["output/okf/references/index.md"],
            "references/evidence.md": release[
                "output/okf/references/evidence.md"
            ],
        },
    )
    assert projection["valid"]
    assert projection["integrity"]
    assert projection["report_integrity"]
    assert projection["archive_integrity"]
    assert projection["artifact_integrity"]
    assert projection["bundle_integrity"]
    assert projection["sources"][0]["title"] == "https://example.test/docs"


def test_public_evidence_refuses_all_selection() -> None:
    module = load_module()
    args = module.parser().parse_args(["--all", "--include-evidence"])

    with pytest.raises(module.PublicationError, match="explicit --run"):
        module.validate_selection(args)


def test_public_evidence_publishes_manifest_last() -> None:
    module = load_module()
    api = BatchApiSimulator()
    fs = FileSystemSimulator({})
    prepared = [
        ("run-a", "output/report.md", b"# Report"),
        ("run-a", "output/okf/index.md", b"index"),
        ("run-a", module.KNOWLEDGE_MANIFEST, b"manifest"),
    ]

    changed = module.publish_prepared(
        api,
        fs,
        "evalstate/public",
        prepared,
        {"run-a"},
        "token",
    )

    assert changed[-1] == f"run-a/{module.KNOWLEDGE_MANIFEST}"
    assert len(api.calls) == 2
    assert api.calls[0][1]["add"] == [
        (b"# Report", "run-a/output/report.md"),
        (b"index", "run-a/output/okf/index.md"),
    ]
    assert api.calls[1][1]["add"] == [
        (b"manifest", f"run-a/{module.KNOWLEDGE_MANIFEST}")
    ]


def test_report_update_requires_refreshing_existing_public_evidence() -> None:
    module = load_module()
    root = "buckets/evalstate/public/run-a"
    fs = FileSystemSimulator(
        {
            f"{root}/output/report.md": b"# Old",
            f"{root}/{module.KNOWLEDGE_MANIFEST}": b"manifest",
        }
    )

    with pytest.raises(module.PublicationError, match="--include-evidence"):
        module.publish_prepared(
            BatchApiSimulator(),
            fs,
            "evalstate/public",
            [("run-a", "output/report.md", b"# New")],
            set(),
            "token",
        )


def test_public_evidence_withdraws_stale_manifest_before_refresh() -> None:
    module = load_module()
    root = "buckets/evalstate/public/run-a"
    fs = FileSystemSimulator(
        {
            f"{root}/output/report.md": b"# Old",
            f"{root}/{module.KNOWLEDGE_MANIFEST}": b"old manifest",
        }
    )
    api = BatchApiSimulator()

    module.publish_prepared(
        api,
        fs,
        "evalstate/public",
        [
            ("run-a", "output/report.md", b"# New"),
            ("run-a", module.KNOWLEDGE_MANIFEST, b"new manifest"),
        ],
        {"run-a"},
        "token",
    )

    assert api.calls[0][1] == {
        "delete": [f"run-a/{module.KNOWLEDGE_MANIFEST}"],
        "token": "token",
    }
    assert api.calls[-1][1]["add"] == [
        (b"new manifest", f"run-a/{module.KNOWLEDGE_MANIFEST}")
    ]


def test_public_evidence_publication_is_idempotent() -> None:
    module = load_module()
    fs = FileSystemSimulator({})
    api = ApplyingBatchApiSimulator(fs)
    report = b"# Report\n\n[Docs](https://example.test/docs)\n"
    prepared = [("run-a", "output/report.md", report)]
    prepared.extend(
        module.prepare_public_evidence(
            prepared,
            "evalstate/research-agent",
        )
    )

    first = module.publish_prepared(
        api,
        fs,
        "evalstate/public",
        prepared,
        {"run-a"},
        "token",
    )
    api.calls.clear()
    second = module.publish_prepared(
        api,
        fs,
        "evalstate/public",
        prepared,
        {"run-a"},
        "token",
    )

    assert first
    assert second == []
    assert api.calls == []


def test_cli_requires_explicit_run_selection() -> None:
    module = load_module()

    with pytest.raises(SystemExit):
        module.parser().parse_args([])
