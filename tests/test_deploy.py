from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
EXPECTED_SCOPES = {
    "inference-api",
    "read-mcp",
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


def test_deployment_sources_are_synced() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_deploy.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
