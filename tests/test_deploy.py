from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EXPECTED_SCOPES = {
    "inference-api",
    "read-mcp",
    "jobs",
    "contribute-repos",
    "write-repos",
    "manage-repos",
}


def scopes(readme: Path) -> set[str]:
    lines = readme.read_text().splitlines()
    start = lines.index("hf_oauth_scopes:") + 1
    return {
        line.removeprefix("  - ") for line in lines[start:] if line.startswith("  - ")
    }


def test_deployments_request_the_approved_scopes() -> None:
    for deployment in ("research-tool-one", "research-agent-two"):
        readme = ROOT / "deploy" / deployment / "README.md"
        assert scopes(readme) == EXPECTED_SCOPES


def test_supported_agent_tracks_current_fast_agent() -> None:
    dockerfile = (ROOT / "deploy/research-agent-two/Dockerfile").read_text()
    config = (ROOT / "research/fast-agent.yaml").read_text()

    assert "fast-agent-mcp" in dockerfile
    assert "fast-agent-mcp==" not in dockerfile
    assert "llm_retries: 5" in config


@pytest.fixture(scope="module")
def built_deployments(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("deploy")
    result = subprocess.run(
        [sys.executable, "scripts/build_deploy.py", "--output", str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_deployment_sources_are_staged_from_canonical_sources(
    built_deployments: Path,
) -> None:
    deployment = built_deployments / "research-agent-two"

    assert (deployment / "fastmcp_research_app.py").read_bytes() == (
        ROOT / "fastmcp_research_app.py"
    ).read_bytes()
    assert (deployment / "research/agent-cards/research.md").read_bytes() == (
        ROOT / "research/agent-cards/research.md"
    ).read_bytes()
    assert not (deployment / "research/sessions").exists()

    legacy = built_deployments / "research-tool-one"
    assert (legacy / "research_app.py").read_bytes() == (
        ROOT / "research/research_app.py"
    ).read_bytes()
    imported = subprocess.run(
        [sys.executable, "-c", "import research_app"],
        cwd=legacy,
        env={**os.environ, "PYTHONPATH": str(legacy)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    template = built_deployments / "research-archive-template"
    assert (template / "archive-template.json").read_bytes() == (
        ROOT / "deploy/research-archive/archive-template.json"
    ).read_bytes()
    assert "Research Archive Template" in (template / "README.md").read_text()


def test_deployed_birch_card_tools_exist_in_renderer(
    built_deployments: Path,
) -> None:
    deployment = built_deployments / "research-agent-two" / "research"
    card = (deployment / "agent-cards" / "birch-html.md").read_text()
    renderer = (deployment / "birch_renderer.py").read_text()

    assert "birch_renderer.py:stage_birch_report" in card
    assert "def stage_birch_report(" in renderer
    assert (deployment / "artifact_contract.py").is_file()


def test_research_card_documents_canonical_sandbox_creation() -> None:
    card = (ROOT / "research/agent-cards/research.md").read_text()

    assert '"cmd": "create"' in card
    assert '"hf://buckets/OWNER/BUCKET/WORKSPACE:/workspace"' in card
    assert "Do not repeat `create` inside `args`" in card
