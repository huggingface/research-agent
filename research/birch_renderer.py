"""Deterministic Birch HTML finalization in a per-job Hugging Face Sandbox."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import posixpath
import re
import shlex
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from fast_agent.tools.environment_transfer import copy_tree
from fast_agent.tools.execution_environment import ShellExecutionRequest
from fast_agent.tools.huggingface_sandbox_environment import (
    HuggingFaceBucketMount,
    HuggingFaceSandboxEnvironment,
)
from fast_agent.tools.local_shell_executor import LocalEnvironment
from huggingface_hub import HfApi

from research.app_artifacts import SAFE_ASSET_MEDIA_TYPES
from research.app_jobs import ResearchJob, current_research_job
from research.research_workspace import (
    ResearchWorkspace,
    current_research_workspace,
)

SKILL_ROOT = Path(__file__).parent / "skills" / "birch-html"
SANDBOX_SKILL_ROOT = "/opt/birch"
SANDBOX_WORKSPACE_ROOT = "/workspace"
BIRCH_STYLE_MARKER = "__BIRCH_SYSTEM_CSS__"
MAX_FINALIZE_ATTEMPTS = 3
PRESENTATION_MANIFEST_VALIDATOR = r"""
import json
import posixpath
import sys
from pathlib import Path

attempt_root = Path(sys.argv[1])
allowed = json.loads(sys.argv[2])
manifest_path = attempt_root / "manifest.json"
validation_path = attempt_root / "validation" / "finalization.md"
validation_path.parent.mkdir(parents=True, exist_ok=True)

errors = []
try:
    manifest = json.loads(manifest_path.read_text())
except Exception as exc:
    errors.append(f"Could not read presentation manifest: {exc}")
    manifest = {}

prefix = attempt_root.as_posix().removeprefix("/workspace/") + "/assets/"
records = manifest.get("artifacts", []) if isinstance(manifest, dict) else []
if not isinstance(records, list):
    errors.append("Presentation manifest artifacts must be a list.")
    records = []
for record in records:
    if not isinstance(record, dict):
        errors.append("Presentation manifest entries must be JSON objects.")
        continue
    path = str(record.get("path") or "")
    candidate = Path(path)
    normalized = posixpath.normpath(path)
    if (
        not path
        or candidate.is_absolute()
        or ".." in candidate.parts
        or normalized.startswith("../")
    ):
        errors.append(f"Invalid workspace-relative presentation path: {path!r}.")
        continue
    path = normalized
    if not path.startswith(prefix):
        continue
    suffix = Path(path).suffix.lower()
    expected = allowed.get(suffix)
    declared = record.get("media_type")
    if expected is None:
        errors.append(
            f"{path} is not a supported presentation asset. "
            "Do not copy output/report.md into assets/. "
            f"Permitted extensions: {', '.join(sorted(allowed))}."
        )
    elif declared and declared != expected:
        errors.append(
            f"{path} declares {declared!r}; expected {expected!r} for {suffix}."
        )

if errors:
    validation_path.write_text(
        "# Presentation finalization validation\n\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\n"
    )
    raise SystemExit("\n".join(errors))

validation_path.write_text(
    "# Presentation finalization validation\n\n"
    "Presentation asset types and media types are valid.\n"
)
"""

SANDBOX_AGENT_CARD = """---
type: agent
name: birch-html-worker
description: Build a polished Birch report from a durable research handoff.
model: $system.html
skills: []
use_history: false
shell: true
cwd: /workspace
---
You are the presentation stage of a durable, multi-sandbox research workflow.

The mounted /workspace directory is the only artifact boundary. Previous
sandboxes are gone. Read the research handoff and preserve its evidence.

Before creating the report:
1. Read /opt/birch/SKILL.md and /opt/birch/resources/template.html.
2. Read the most relevant recipe or recipes under /opt/birch/recipes/.
3. Read /workspace/output/report.md.
4. Read /workspace/scratch/research/manifest.json and any useful declared
   research data, scripts, notes, or assets.

You may generate charts, diagrams, images, and other browser-safe assets when
they improve the report. Reuse research assets when suitable, or regenerate
them from persisted research data. Install libraries inside this sandbox when
needed. Never depend on /tmp after this invocation.

Write a complete self-contained Birch HTML draft to the exact path supplied in
the user prompt. Use the trusted __BIRCH_SYSTEM_CSS__ marker and canonical Birch
classes; do not recreate the design system in custom CSS. Put file assets in
the attempt's assets/ directory and reference them as relative assets/... URLs.
Never reference /tmp, /workspace, file://, or ../scratch from HTML.

/workspace/output/report.md is the canonical Markdown report. Never copy it to
the attempt assets/ directory and never declare assets/report.md. The finalized
HTML and Markdown reports are published as siblings, so use href="report.md"
for a visible link to the canonical Markdown report.

Only declare presentation assets with these extensions:
.avif, .csv, .gif, .jpeg, .jpg, .json, .png, .svg, .webp.

Write the attempt manifest last, after every artifact is durable. Return only a
concise completion summary.
"""


def read_birch_skill_file(path: str = "SKILL.md") -> str:
    """Read one file from the declared Birch Skill directory."""
    relative = PurePosixPath(path.strip())
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Birch Skill paths must be relative and cannot traverse.")
    resolved = (SKILL_ROOT / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(SKILL_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("Birch Skill path is outside the Skill directory.") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"Birch Skill file does not exist: {relative}")
    return resolved.read_text(encoding="utf-8")


def stage_birch_report(
    title: str,
    lede: str,
    metrics: list[dict[str, str]],
    rankings: list[dict[str, str]],
    findings: list[dict[str, str]],
    caveats: list[str],
    sources: list[dict[str, str]],
) -> str:
    """Stage a bounded canonical Birch report in the current workspace.

    Args:
        title: Findings-first report title.
        lede: Two or three sentences with scope and strongest takeaway.
        metrics: Up to six items with ``label``, ``value``, and optional ``note``.
        rankings: Up to twelve rows with ``rank``, ``label``, ``value``, and
            optional ``note``.
        findings: Up to eight items with ``title`` and ``body``.
        caveats: Up to six concise methodology or interpretation caveats.
        sources: Up to twelve distinct links with ``label`` and absolute ``url``.

    The output path is fixed to ``scratch/report.html``. Model-provided text is
    escaped and URLs are validated; arbitrary HTML and paths are not accepted.
    """
    workspace = current_research_workspace.get()
    if workspace is None or workspace.bearer_token is None:
        raise RuntimeError("No authenticated research workspace is active.")

    draft = _render_birch_report(
        title=title,
        lede=lede,
        metrics=metrics,
        rankings=rankings,
        findings=findings,
        caveats=caveats,
        sources=sources,
        markdown_url=(
            f"https://huggingface.co/buckets/{workspace.bucket_id}/tree/"
            f"{workspace.session_id}/output/report.md"
        ),
    )
    remote_path = f"{workspace.session_id}/scratch/report.html"
    HfApi().batch_bucket_files(
        workspace.bucket_id,
        add=[(draft.encode("utf-8"), remote_path)],
        token=workspace.bearer_token,
    )
    job = current_research_job.get()
    if job is not None:
        job.add_event("Staged canonical Birch HTML draft", kind="Report")
    return f"Staged {workspace.root}scratch/report.html ({len(draft)} bytes)"


def _render_birch_report(
    *,
    title: str,
    lede: str,
    metrics: list[dict[str, str]],
    rankings: list[dict[str, str]],
    findings: list[dict[str, str]],
    caveats: list[str],
    sources: list[dict[str, str]],
    markdown_url: str,
) -> str:
    title = _bounded_text(title, "title", 180)
    lede = _bounded_text(lede, "lede", 900)
    metrics = _bounded_records(metrics, "metrics", 6)
    rankings = _bounded_records(rankings, "rankings", 12)
    findings = _bounded_records(findings, "findings", 8)
    caveats = [_bounded_text(item, "caveat", 500) for item in _bounded_list(caveats, 6)]
    sources = _bounded_records(sources, "sources", 12)

    metric_cards = "\n".join(_metric_card(item) for item in metrics)
    ranking_chart = _ranking_chart(rankings)
    ranking_rows = "\n".join(
        f"""<tr>
  <td class="num">{_field(item, "rank", 16)}</td>
  <td class="entity">{_field(item, "label", 160)}</td>
  <td class="num">{_field(item, "value", 100)}</td>
  <td class="note">{_field(item, "note", 240, required=False)}</td>
</tr>"""
        for item in rankings
    )
    finding_cards = "\n".join(
        f"""<article class="card stack" data-gap="sm">
  <h3>{_field(item, "title", 180)}</h3>
  <p>{_field(item, "body", 900)}</p>
</article>"""
        for item in findings
    )
    caveat_items = "\n".join(f"<li>{item}</li>" for item in caveats)
    source_items = [
        (
            _field(item, "label", 180),
            _safe_url(_raw_field(item, "url", required=True)),
        )
        for item in sources
    ]
    source_items.append(("Complete Markdown report", _safe_url(markdown_url)))
    deduped_sources = dict((url, label) for label, url in source_items)
    source_links = "\n".join(
        f'<li><a href="{html.escape(url, quote=True)}">{label}</a></li>'
        for url, label in deduped_sources.items()
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style data-birch-system>{BIRCH_STYLE_MARKER}</style>
  </head>
  <body>
    <main class="page stack" data-gap="lg">
      <header class="stack" data-gap="sm">
        <div class="eyebrow">Research Dispatch</div>
        <h1>{title}</h1>
        <p class="lede">{lede}</p>
      </header>
      <section class="section stack" data-gap="lg">
        <div class="section-head"><div><span class="eyebrow">At a glance</span><h2>Headline metrics</h2></div></div>
        <div class="auto-grid" style="--grid-min: 220px">{metric_cards}</div>
      </section>
      <section class="section stack" data-gap="lg">
        <div class="section-head"><div><span class="eyebrow">Comparison</span><h2>Leading entities</h2></div></div>
        {ranking_chart}
        <div class="numeric-table-wrap"><table class="numeric-table">
          <thead><tr><th class="num">Rank</th><th>Entity</th><th class="num">Value</th><th>Context</th></tr></thead>
          <tbody>{ranking_rows}</tbody>
        </table></div>
      </section>
      <section class="section stack" data-gap="lg">
        <div class="section-head"><div><span class="eyebrow">Findings</span><h2>What changed</h2></div></div>
        <div class="auto-grid" style="--grid-min: 300px">{finding_cards}</div>
      </section>
      <section class="section stack" data-gap="md">
        <div class="section-head"><div><span class="eyebrow">Interpretation</span><h2>Caveats and method</h2></div></div>
        <aside class="callout" data-tone="warning"><ul class="plain-list">{caveat_items}</ul></aside>
      </section>
      <section class="section stack" data-gap="md">
        <div class="section-head"><div><span class="eyebrow">Evidence</span><h2>Sources and detailed data</h2></div></div>
        <ul class="plain-list">{source_links}</ul>
      </section>
    </main>
  </body>
</html>
"""


def _metric_card(item: dict[str, str]) -> str:
    raw_value = _raw_field(item, "value", required=True)
    value_class = "stat-value" if _is_compact_metric(raw_value) else "card-title"
    return f"""<article class="card stat-card stack" data-gap="xs">
  <div class="caption">{_field(item, "label", 100)}</div>
  <div class="{value_class}">{_bounded_text(raw_value, "value", 100)}</div>
  {_optional_paragraph(item, "note", "muted", 240)}
</article>"""


def _is_compact_metric(value: str) -> bool:
    """Reserve oversized KPI typography for short numeric values."""
    return len(value) <= 14 and bool(
        re.fullmatch(
            r"[~≈<>+\-]?\s*[$€£¥]?\s*[\d.,]+\s*(?:[%×xKMBTkmbt]|ms|s|m|h|d)?", value
        )
    )


def _ranking_chart(rankings: list[dict[str, str]]) -> str:
    parsed = [
        (item, _parse_numeric_value(_raw_field(item, "value", required=True)))
        for item in rankings
    ]
    comparable = [(item, value) for item, value in parsed if value is not None]
    if len(comparable) < 3:
        return ""

    maximum = max(value for _, value in comparable)
    if maximum <= 0:
        return ""

    rows = "\n".join(
        f"""<div class="metric-row">
  <span class="caption">{_field(item, "label", 160)}</span>
  <div class="meter"><span style="--value: {max(1, round(value / maximum * 100))}%"></span></div>
  <code>{_field(item, "value", 100)}</code>
</div>"""
        for item, value in comparable
    )
    return f"""<div class="panel chart-panel stack" data-gap="md">
  <div><span class="eyebrow">Relative scale</span><h3>Ranked comparison</h3></div>
  <div class="metric-list" style="--metric-label: 180px; --metric-value: 88px">{rows}</div>
  <p class="chart-caption">Bars are normalized to the largest listed value; exact source values appear beside each bar and in the table below.</p>
</div>"""


def _parse_numeric_value(value: str) -> float | None:
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
    if match is None:
        return None
    number = float(match.group().replace(",", ""))
    suffix = value[match.end() :].lstrip().lower()[:1]
    multiplier = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}.get(suffix, 1)
    result = number * multiplier
    return result if result >= 0 else None


def _bounded_list(items: list[object], maximum: int) -> list[object]:
    if len(items) > maximum:
        raise ValueError(f"Expected at most {maximum} items, received {len(items)}")
    return items


def _bounded_records(
    items: list[dict[str, str]],
    name: str,
    maximum: int,
) -> list[dict[str, str]]:
    _bounded_list(items, maximum)
    if not items:
        raise ValueError(f"{name} must not be empty")
    return items


def _bounded_text(value: str, name: str, maximum: int) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return html.escape(text)


def _raw_field(
    item: dict[str, str],
    key: str,
    *,
    required: bool,
) -> str:
    value = str(item.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"Missing required {key!r} field")
    return value


def _field(
    item: dict[str, str],
    key: str,
    maximum: int,
    *,
    required: bool = True,
) -> str:
    value = _raw_field(item, key, required=required)
    return _bounded_text(value, key, maximum) if value else ""


def _optional_paragraph(
    item: dict[str, str],
    key: str,
    css_class: str,
    maximum: int,
) -> str:
    value = _field(item, key, maximum, required=False)
    return f'<p class="{css_class}">{value}</p>' if value else ""


def _safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https", "hf"} or not parsed.netloc:
        raise ValueError(f"Source URL must be absolute and trusted: {value!r}")
    return value


async def generate_birch_report(
    workspace: ResearchWorkspace,
    *,
    attempt: int,
) -> None:
    """Run a stateless HTML worker in a fresh session-mounted sandbox."""
    if workspace.bearer_token is None:
        raise RuntimeError("A Hugging Face token is required for HTML generation.")

    attempt_root = f"scratch/presentation/attempts/{attempt}"
    report_path = f"{attempt_root}/report.html"
    manifest_path = f"{attempt_root}/manifest.json"
    trace_path = f"scratch/traces/html-generator-attempt-{attempt}.atif.json"
    result_path = f"scratch/traces/html-generator-attempt-{attempt}.history.json"
    prompt = f"""Build the HTML presentation for this research workspace.

Inputs:
- /workspace/output/report.md
- /workspace/scratch/research/manifest.json
- all artifacts declared by that research manifest

Outputs for attempt {attempt}:
- /workspace/{report_path}
- optional assets under /workspace/{attempt_root}/assets/
- /workspace/{manifest_path}, written last

The presentation manifest must be JSON with this shape:
{{
  "schema_version": 1,
  "stage": "presentation",
  "attempt": {attempt},
  "status": "complete",
  "entrypoint": "{report_path}",
  "artifacts": [
    {{"path": "{report_path}", "media_type": "text/html", "role": "report"}}
  ]
}}

Declare every generated asset using its workspace-relative path. Generate
charts when the persisted evidence supports a useful visualization. Pair
charts with exact values or accessible explanatory text.

`/workspace/output/report.md` is canonical input, not a presentation asset.
Do not copy or declare it under assets/. Link the final sibling report with
href="report.md". Assets are limited to:
.avif, .csv, .gif, .jpeg, .jpg, .json, .png, .svg, .webp.
"""
    if attempt > 1:
        prompt += f"""
This is retry attempt {attempt}. Inspect the preceding attempt and its durable
validation findings under:
- /workspace/scratch/presentation/attempts/{attempt - 1}/

Correct those findings rather than repeating the same presentation.
"""

    sandbox = _agent_sandbox_environment(workspace)
    completed = False
    try:
        await _open_sandbox(sandbox)
        await copy_tree(
            LocalEnvironment(
                logger=logging.getLogger(__name__),
                working_directory=SKILL_ROOT.parent,
            ),
            SKILL_ROOT.name,
            sandbox,
            SANDBOX_SKILL_ROOT,
        )
        await sandbox.write_text("/opt/html-agent.md", SANDBOX_AGENT_CARD)
        await sandbox.write_text("/opt/html-prompt.md", prompt)
        await sandbox.write_text(
            "/opt/validate-presentation-manifest.py",
            PRESENTATION_MANIFEST_VALIDATOR,
        )
        await sandbox.write_text(
            "/opt/fast-agent.yaml",
            (Path(__file__).parent / "fast-agent.yaml").read_text(),
        )
        package = os.getenv("BIRCH_FAST_AGENT_PACKAGE", "fast-agent-mcp")
        command = (
            f"uvx {shlex.quote(package)} go "
            "--no-home --config-path /opt/fast-agent.yaml "
            "--card /opt/html-agent.md --agent birch-html-worker "
            "--model '$system.html' --shell "
            "--prompt-file /opt/html-prompt.md "
            f"--trajectory-output {shlex.quote(_sandbox_path(trace_path))} "
            f"--results {shlex.quote(_sandbox_path(result_path))} "
            f"--timeout {int(os.getenv('BIRCH_AGENT_TIMEOUT', '900'))} --quiet"
        )
        await _run(
            sandbox,
            command,
            timeout=float(os.getenv("BIRCH_AGENT_TIMEOUT", "900")) + 60,
        )
        try:
            await _run(
                sandbox,
                "python /opt/validate-presentation-manifest.py "
                f"{shlex.quote(_sandbox_path(attempt_root))} "
                f"{shlex.quote(json.dumps(SAFE_ASSET_MEDIA_TYPES, sort_keys=True))}",
                timeout=60,
            )
            await _validate(
                sandbox,
                _sandbox_path(report_path),
                report_root=_sandbox_path(f"{attempt_root}/validation"),
                fail_on_warn=True,
            )
        except Exception:
            for diagnostic in (
                f"{attempt_root}/validation/finalization.md",
                f"{attempt_root}/validation/check.md",
            ):
                try:
                    await _wait_for_bucket_file(
                        workspace,
                        diagnostic,
                        timeout=15,
                    )
                except Exception:
                    pass
            raise
        completed = True
    finally:
        await asyncio.shield(sandbox.close())

    if completed:
        await asyncio.gather(
            _wait_for_bucket_file(workspace, report_path),
            _wait_for_bucket_file(workspace, manifest_path),
            _wait_for_bucket_file(workspace, trace_path),
        )


def _agent_sandbox_environment(
    workspace: ResearchWorkspace,
) -> HuggingFaceSandboxEnvironment:
    return HuggingFaceSandboxEnvironment(
        image=os.getenv(
            "BIRCH_AGENT_SANDBOX_IMAGE",
            "ghcr.io/astral-sh/uv:python3.13-bookworm",
        ),
        flavor=os.getenv("BIRCH_SANDBOX_FLAVOR", "cpu-basic"),
        cwd=SANDBOX_WORKSPACE_ROOT,
        idle_timeout=os.getenv("BIRCH_SANDBOX_IDLE_TIMEOUT", "10m"),
        token=workspace.bearer_token,
        forward_hf_token=True,
        bucket_mounts=(
            HuggingFaceBucketMount(
                source=workspace.bucket_id,
                path=workspace.session_id,
                mount_path=SANDBOX_WORKSPACE_ROOT,
                read_only=False,
            ),
        ),
    )


async def finalize_birch_artifact(
    draft_path: str = "scratch/report.html",
    output_path: str = "output/report.html",
) -> str:
    """Finalize and validate a Birch draft in an isolated sandbox.

    Paths must be relative to the current research session root. The tool mounts
    exactly that session at ``/workspace``; do not include bucket or session IDs.
    """
    workspace = current_research_workspace.get()
    if workspace is None:
        raise RuntimeError("No authenticated research workspace is active.")
    job = current_research_job.get()
    _claim_finalize_attempt(job)

    draft = _workspace_path(workspace, draft_path, directory="scratch")
    output = _workspace_path(workspace, output_path, directory="output")
    await BirchSandboxRenderer().render(workspace, draft=draft, output=output)

    uri = f"{workspace.root}{output}"
    https_url = (
        f"https://huggingface.co/buckets/{workspace.bucket_id}/tree/"
        f"{workspace.session_id}/{output}"
    )
    if job is not None:
        job.html_report_uri = uri
        job.html_report_url = https_url
        job.add_event("The HTML report was produced.", kind="Report")
    return f"Birch HTML artifact finalized:\n- {uri}\n- {https_url}"


class BirchSandboxRenderer:
    """Copy the trusted renderer into a sandbox and finalize one mounted draft."""

    async def render(
        self,
        workspace: ResearchWorkspace,
        *,
        draft: str,
        output: str,
    ) -> None:
        if not SKILL_ROOT.is_dir():
            raise RuntimeError(f"Birch Skill directory is missing: {SKILL_ROOT}")
        if workspace.bearer_token is None:
            raise RuntimeError(
                "A Hugging Face token is required to create the sandbox."
            )

        sandbox = _sandbox_environment(workspace)
        finalized = False
        try:
            await _open_sandbox(sandbox)
            await copy_tree(
                LocalEnvironment(
                    logger=logging.getLogger(__name__),
                    working_directory=SKILL_ROOT.parent,
                ),
                SKILL_ROOT.name,
                sandbox,
                SANDBOX_SKILL_ROOT,
            )

            sandbox_draft = _sandbox_path(draft)
            sandbox_output = _sandbox_path(output)
            if not await sandbox.exists(sandbox_draft):
                raise FileNotFoundError(
                    f"Birch draft does not exist in this session: {draft}"
                )
            draft_html = await sandbox.read_text(sandbox_draft)
            await sandbox.write_text(sandbox_draft, _prepare_html_draft(draft_html))

            await _run(
                sandbox,
                "python "
                f"{shlex.quote(f'{SANDBOX_SKILL_ROOT}/scripts/finish_birch_html.py')} "
                f"{shlex.quote(sandbox_draft)}",
            )
            await _validate(sandbox, sandbox_draft)
            await _run(
                sandbox,
                f"mkdir -p {shlex.quote(posixpath.dirname(sandbox_output))} && "
                f"cp {shlex.quote(sandbox_draft)} {shlex.quote(sandbox_output)}",
            )
            finalized = True
        finally:
            await asyncio.shield(sandbox.close())
        if finalized:
            await _wait_for_bucket_file(workspace, output)


def _claim_finalize_attempt(job: ResearchJob | None) -> None:
    if job is None:
        return
    if job.birch_finalize_attempts >= MAX_FINALIZE_ATTEMPTS:
        raise RuntimeError(
            "Birch finalization retry limit reached. Return the latest validation "
            "findings to the Researcher instead of retrying again."
        )
    job.birch_finalize_attempts += 1


def _sandbox_environment(workspace: ResearchWorkspace) -> HuggingFaceSandboxEnvironment:
    return HuggingFaceSandboxEnvironment(
        image=os.getenv("BIRCH_SANDBOX_IMAGE", "python:3.12"),
        flavor=os.getenv("BIRCH_SANDBOX_FLAVOR", "cpu-basic"),
        cwd=SANDBOX_WORKSPACE_ROOT,
        idle_timeout=os.getenv("BIRCH_SANDBOX_IDLE_TIMEOUT", "10m"),
        token=workspace.bearer_token,
        bucket_mounts=(
            HuggingFaceBucketMount(
                source=workspace.bucket_id,
                path=workspace.session_id,
                mount_path=SANDBOX_WORKSPACE_ROOT,
                read_only=False,
            ),
        ),
    )


def _workspace_path(
    workspace: ResearchWorkspace,
    value: str,
    *,
    directory: str,
) -> str:
    path = value.strip()
    if path.startswith("hf://"):
        if not path.startswith(workspace.root):
            raise ValueError("Artifact path belongs to a different research session.")
        path = path.removeprefix(workspace.root)

    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Artifact paths must be relative to the current session.")
    normalized = posixpath.normpath(str(candidate))
    if normalized in {"", "."} or not normalized.startswith(f"{directory}/"):
        raise ValueError(f"Artifact path must be inside {directory}/.")
    return normalized


def _sandbox_path(relative_path: str) -> str:
    return posixpath.join(SANDBOX_WORKSPACE_ROOT, relative_path)


def _prepare_html_draft(html: str) -> str:
    prepared = html.strip()
    if prepared.startswith("```") and prepared.endswith("```"):
        lines = prepared.splitlines()
        prepared = "\n".join(lines[1:-1]).strip()

    lowered = prepared.lower()
    required = ("<!doctype", "<html", "<head", "</head>", "<body", "</body>", "</html>")
    missing = [token for token in required if token not in lowered]
    if missing:
        raise ValueError(
            "Birch draft must be a complete HTML document; missing "
            + ", ".join(missing)
            + "."
        )

    if "data-birch-system" not in lowered:
        style = f"<style data-birch-system>{BIRCH_STYLE_MARKER}</style>"
        if BIRCH_STYLE_MARKER in prepared:
            prepared = prepared.replace(BIRCH_STYLE_MARKER, style, 1)
        else:
            head_end = prepared.lower().find("</head>")
            prepared = f"{prepared[:head_end]}  {style}\n{prepared[head_end:]}"
    return prepared.rstrip() + "\n"


def _bucket_object_path(workspace: ResearchWorkspace, relative_path: str) -> str:
    return posixpath.join(workspace.session_id, relative_path)


async def _open_sandbox(sandbox: HuggingFaceSandboxEnvironment) -> None:
    open_task = asyncio.create_task(sandbox.open())
    try:
        await asyncio.shield(open_task)
    except asyncio.CancelledError:
        try:
            await open_task
        finally:
            await sandbox.close()
        raise


async def _wait_for_bucket_file(
    workspace: ResearchWorkspace,
    relative_path: str,
    *,
    timeout: float | None = None,
) -> None:
    expected = _bucket_object_path(workspace, relative_path)
    timeout = timeout or float(os.getenv("BIRCH_PERSIST_TIMEOUT", "60"))
    deadline = asyncio.get_running_loop().time() + timeout
    api = HfApi(token=workspace.bearer_token)

    while True:
        items = await asyncio.to_thread(
            lambda: list(
                api.list_bucket_tree(
                    workspace.bucket_id,
                    prefix=expected,
                    recursive=True,
                    token=workspace.bearer_token,
                )
            )
        )
        if any(
            getattr(item, "path", None) == expected
            and getattr(item, "type", None) == "file"
            and int(getattr(item, "size", 0) or 0) > 0
            for item in items
        ):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(
                f"Finalized Birch artifact was not persisted to {expected}."
            )
        await asyncio.sleep(1)


async def _run(
    sandbox: HuggingFaceSandboxEnvironment,
    command: str,
    *,
    timeout: float = 120,
) -> None:
    request = ShellExecutionRequest(
        command=command,
        terminate_after_idle=False,
    )
    try:
        execution = await asyncio.wait_for(
            sandbox.execute(request),
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"Birch sandbox command timed out: {command}") from exc
    result = execution.result
    if execution.timed_out:
        raise TimeoutError(f"Birch sandbox command timed out: {command}")
    if result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Birch sandbox command failed: {detail}")


async def _validate(
    sandbox: HuggingFaceSandboxEnvironment,
    artifact: str,
    *,
    report_root: str = "/tmp",
    fail_on_warn: bool = False,
) -> None:
    await _run(sandbox, f"mkdir -p {shlex.quote(report_root)}")
    fail_flag = " --fail-on-warn" if fail_on_warn else ""
    command = (
        "python "
        f"{shlex.quote(f'{SANDBOX_SKILL_ROOT}/scripts/check_birch_renderings.py')} "
        f"--artifact {shlex.quote(artifact)} --no-capture "
        f"--out {shlex.quote(f'{report_root}/check.json')} "
        f"--markdown {shlex.quote(f'{report_root}/check.md')} "
        f"--screenshots-dir {shlex.quote(f'{report_root}/screenshots')}"
        f"{fail_flag}"
    )
    execution = await sandbox.execute(
        ShellExecutionRequest(command=command, timeout=120)
    )
    if execution.timed_out:
        raise TimeoutError("Birch validation timed out.")
    if execution.result.exit_code == 0:
        return
    try:
        report = (await sandbox.read_text(f"{report_root}/check.md")).strip()
    except Exception:
        report = execution.result.stderr.strip() or execution.result.stdout.strip()
    raise RuntimeError(f"Birch validation failed:\n{report[:8000]}")
