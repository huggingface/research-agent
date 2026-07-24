from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from research.app_jobs import ResearchJob
from research.app_observability import (
    JobProgressHandler,
    _archive_target,
    archive_session,
    capture_markdown_report,
)
from research.research_workspace import (
    ResearchWorkspace,
    current_research_workspace,
)


@pytest.mark.asyncio
async def test_internal_progress_is_kept_in_a_two_line_activity_roll() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")
    handler = JobProgressHandler(job)
    call_id = await handler.on_tool_start(
        "agent_loop",
        "researcher",
        None,
        "call",
    )

    await handler.on_tool_progress(call_id, 3, None, "step 3 (llm)")

    roll = job.snapshot()["activity_roll"]
    assert [event["message"] for event in roll] == [
        "researcher/agent_loop: step 3 (llm)",
        "researcher/agent_loop: started",
    ]
    assert job.activity_source == "researcher/agent_loop"


@pytest.mark.asyncio
async def test_hugging_face_tool_events_keep_compact_progress_detail() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")
    handler = JobProgressHandler(job)
    call_id = await handler.on_tool_start(
        "hf_fs",
        "hf",
        {"cmd": "search"},
        "call",
    )

    await handler.on_tool_complete(call_id, True, None, None)

    assert job.activity_source == "researcher/agent_loop"
    assert job.events[-1]["kind"] == "Activity"
    assert job.events[-1]["message"] == "hf/hf_fs: completed"


@pytest.mark.asyncio
async def test_common_tool_errors_are_rephrased_without_internal_codes() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice")
    handler = JobProgressHandler(job)
    call_id = await handler.on_tool_start("hf_fs", "hf", {"cmd": "search"}, "call")

    await handler.on_tool_complete(
        call_id,
        False,
        None,
        "EINVAL: search requires a positional query or --query",
    )

    assert job.events[-1]["message"] == (
        "A Hugging Face search request was missing its query."
    )


@pytest.mark.asyncio
async def test_birch_delegation_exposes_report_generation_phase() -> None:
    job = ResearchJob(id="job", topic="topic", owner_id="alice", status="running")
    handler = JobProgressHandler(job)

    call_id = await handler.on_tool_start(
        "birch-html[1]",
        "agent",
        {},
        "call",
    )

    assert job.phase == "reporting"
    assert "HTML report is now being produced" in job.activity_summary

    await handler.on_tool_complete(call_id, True, None, None)

    assert job.phase == "wrapping_up"
    assert "HTML reports are complete" in job.activity_summary


@pytest.mark.asyncio
async def test_markdown_report_is_captured_from_current_session() -> None:
    workspace = ResearchWorkspace(
        username="alice",
        session_id="research-abc",
        bucket_id="alice/research-agent",
        root="hf://buckets/alice/research-agent/research-abc/",
        scratch="hf://buckets/alice/research-agent/research-abc/scratch/",
        output="hf://buckets/alice/research-agent/research-abc/output/",
        bucket_created=False,
        marker_paths=(),
        bearer_token="token",
        archive_space_id="alice/research-agent",
        archive_space_url="https://huggingface.co/spaces/alice/research-agent",
        archive_app_url="https://alice-research-agent.hf.space",
        archive_status="ready",
        archive_template_version="1.0.0",
        archive_installed_version="1.0.0",
    )
    job = ResearchJob(id="research-abc", topic="topic", owner_id="alice")

    async def read(current: ResearchWorkspace) -> str:
        assert current is workspace
        return "# Report\n\nVerified result."

    token = current_research_workspace.set(workspace)
    try:
        await capture_markdown_report(job, reader=read)
    finally:
        current_research_workspace.reset(token)

    assert job.markdown_report == "# Report\n\nVerified result."
    assert job.markdown_report_uri == f"{workspace.output}report.md"
    assert job.archive_space_url == workspace.archive_space_url
    assert job.archive_app_url == workspace.archive_app_url
    assert job.archive_template_version == "1.0.0"
    assert job.events[-1]["kind"] == "Report"


class ArchiveApiSimulator:
    def __init__(self, *, private: bool) -> None:
        self.private = private
        self.tokens: list[str] = []

    def bucket_info(self, bucket_id: str, *, token: str) -> SimpleNamespace:
        assert bucket_id == "alice/private-research-sessions"
        self.tokens.append(token)
        return SimpleNamespace(private=self.private)


class _ArchiveWriter(io.BytesIO):
    def __init__(self, destination: str, files: dict[str, bytes]) -> None:
        super().__init__()
        self.destination = destination
        self.files = files

    def close(self) -> None:
        if not self.closed:
            self.files[self.destination] = self.getvalue()
        super().close()


class ArchiveFilesystemSimulator:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def open(self, destination: str, mode: str) -> _ArchiveWriter:
        assert mode == "wb"
        return _ArchiveWriter(destination, self.files)


def test_private_archive_preserves_raw_session_and_codex_trace(tmp_path) -> None:
    job = ResearchJob(id="research-abc", topic="secret prompt", owner_id="alice")
    session = tmp_path / "sessions" / job.harness_session_id
    session.mkdir(parents=True)
    (session / "session.json").write_text('{"topic":"secret prompt"}')
    (session / "history_research.json").write_text('{"messages":[]}')
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"type":"user","message":"secret prompt"}\n')
    api = ArchiveApiSimulator(private=True)
    filesystem = ArchiveFilesystemSimulator()

    uri = archive_session(
        job,
        tmp_path,
        trace,
        target=_archive_target("hf://buckets/alice/private-research-sessions/archive"),
        token="archive-only-token",
        api=api,
        filesystem=filesystem,
    )

    root = "hf://buckets/alice/private-research-sessions/archive"
    assert uri == f"{root}/research-traces/{job.id}/trace.jsonl"
    assert filesystem.files == {
        f"{root}/{job.id}/history_research.json": b'{"messages":[]}',
        f"{root}/{job.id}/session.json": b'{"topic":"secret prompt"}',
        uri: b'{"type":"user","message":"secret prompt"}\n',
    }
    assert api.tokens == ["archive-only-token"]


def test_archive_refuses_public_bucket(tmp_path) -> None:
    job = ResearchJob(id="research-abc", topic="topic", owner_id="alice")
    (tmp_path / "sessions" / job.harness_session_id).mkdir(parents=True)

    with pytest.raises(RuntimeError, match="public bucket"):
        archive_session(
            job,
            tmp_path,
            tmp_path / "trace.jsonl",
            target=_archive_target("hf://buckets/alice/private-research-sessions"),
            token="archive-only-token",
            api=ArchiveApiSimulator(private=False),
            filesystem=ArchiveFilesystemSimulator(),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://huggingface.co/buckets/alice/archive",
        "hf://datasets/alice/archive",
        "hf://buckets/alice",
    ],
)
def test_archive_url_requires_bucket_owner_and_name(url: str) -> None:
    with pytest.raises(ValueError, match="hf://buckets"):
        _archive_target(url)
