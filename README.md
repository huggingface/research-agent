# Hugging Face Researcher

A `fast-agent` research application for Hugging Face.

## What is configured

- `research/fast-agent.yaml` is the local fast-agent home.
- The MCP target `hf` connects to `https://huggingface.co/mcp`.
- `research/agent-cards/researcher.md` lets you publish/run the same researcher
  declaratively.
- `research/skills/birch-html/` is a vendored copy of the
  [Birch HTML skill](https://github.com/evalstate/birch-html/tree/main/skill)
  used by the report-writing subagent.
- `research_app.py` is a custom harness app entrypoint. It intercepts opened
  sessions/invocations, derives the user and session id, verifies/creates the
  user's Hugging Face bucket, writes marker files, and injects the working path
  `hf://buckets/<username>/research-agent/<session-id>/` with `scratch/` and
  `output/` subdirectories.

## Prerequisites

Use the adjacent fast-agent checkout when running from this workspace, for
example:

```bash
uv run --project ../fast-agent python agent.py --model "$MODEL"
```

For private Hugging Face MCP or bucket access, authenticate with either:

```bash
export HF_TOKEN=hf_...
# or: hf auth login
```

### Private session archive

Completed, failed, and cancelled jobs always export a local Codex JSONL trace.
On Hugging Face Spaces, prefer mounting a private bucket directly at the
FastAgent session directory:

```bash
hf spaces volumes set <owner>/<space> \
  -v hf://buckets/<owner>/<private-bucket>:/app/research/sessions
```

This persists the raw sessions and `research-traces/` exports without placing
any archive token in the application environment.

For deployments without a bucket volume, use the optional explicit archiver:

```bash
export RESEARCH_ARCHIVE_HF_URL=hf://buckets/<owner>/<private-bucket>
export RESEARCH_ARCHIVE_TOKEN=hf_...
```

Use a dedicated fine-grained token with write access only to the archive
bucket. The app uses this token only inside the trace archiver: it is not copied
to `HF_TOKEN`, caller auth, MCP auth, workspace context, prompts, or
model-visible tools. A missing bucket is created private; an existing public
bucket is rejected.

## Run in the TUI

```bash
uv run --project ../fast-agent fast-agent go \
  --home research \
  --agent-cards research/agent-cards \
  --agent research
```

This is the normal fast-agent TUI path. For local interactive use that must go
through the same harness app intercept and bucket verification as MCP serving,
use the minimal harness runner instead:

```bash
uv run --project ../fast-agent python harness_chat.py
```

## Run one-off with the home/card

```bash
fast-agent go \
  --home research \
  --agent-cards research/agent-cards \
  --agent research \
  --message "Research the current Hugging Face MCP capabilities and write report.md"
```

## Publish as an MCP server

Use the managed fast-agent server. This checkout of `../fast-agent` was adjusted
so managed MCP publication still exposes AgentCard tools when
`harness_app.entrypoint` is configured.

```bash
uv run --project ../fast-agent fast-agent serve \
  --home research \
  --agent-cards research/agent-cards \
  --transport http \
  --host 127.0.0.1 \
  --port 8723 \
  --instance-scope request
```

For multi-turn research, prefer `connection` scope:

```bash
uv run --project ../fast-agent fast-agent serve \
  --home research \
  --agent-cards research/agent-cards \
  --transport http \
  --host 127.0.0.1 \
  --port 8723 \
  --instance-scope connection
```

`fast-agent serve` does not have a `--agent` option. The `research` AgentCard is
marked `default: true`, so it is the published/default agent. If you add more
cards later, use the card-loading options to control what is exposed.

The server exposes:

- `research` — structured research job, routed through the harness intercept

FastMCP App runs are caller-bound and retained in memory for 24 hours after
completion. Reopening an old Claude Code chat renders the original run while it
is retained. After expiry or a server restart, the historical app displays an
unavailable message and never starts replacement research automatically.

## Read the example

Start with `research/research_runner.py`. Its `invoke()` method is the complete
fast-agent integration:

```python
with harness.request_context(auth=auth):
    async with harness.app().open(
        AppOpenRequest(session_id=job.id, agent="researcher")
    ) as session:
        response = await session.invoke(
            AgentRequest.text(
                job.topic,
                agent="researcher",
                session_id=job.id,
                auth=auth,
            )
        )
```

Everything else is an app concern kept outside that path:

| File | Responsibility |
| --- | --- |
| `fastmcp_server.py` | FastMCP App tools and server wiring |
| `research_runner.py` | Protocol-neutral Harness invocation |
| `app_jobs.py` | Replay-safe job handles, ownership, and expiry |
| `app_ui.py` | Prefab presentation |
| `app_auth.py` | OAuth at the MCP boundary |
| `app_observability.py` | Optional timeline and trace hooks |
| `research_app.py` | Harness interceptor that prepares the user workspace |
| `activity_hooks.py` | Captures exposed reasoning and tool intent after LLM steps |
| `activity_narrator.py` | Schedules rolling summaries with the fast model |

### Live activity narrative

The FastMCP App keeps a concise rolling description of the Researcher's
current work. The Researcher AgentCard's `after_llm_call` hook captures the latest
provider-exposed reasoning, visible response text, and sanitized tool calls.
`ActivityNarrator` updates the narrative after the first LLM step, every three
steps, after 30 seconds of pending activity, and on the final response.

Narration runs through the separate no-tools `activity-summarizer` AgentCard
using `$system.fast` and a distinct Harness session, so it does not block or
modify the main research tool loop. Each update receives only the previous
narrative and latest captured LLM batch; tool results are not included.

For an ordinary MCP App call that completes before its tool call returns, use
`HarnessMCPAdapter.invoke_agent(ctx=...)`; it handles MCP auth, progress, and
session translation. This example uses the explicit Harness API because the
research job continues after `start_research` returns, so it must not retain a
request-scoped FastMCP `Context`.

## Deployment bundles

`deploy/` contains only deployment-specific source such as Dockerfiles, Space
metadata, and configuration. Build a self-contained upload context from those
files and the canonical application sources with:

```bash
uv run --project ../fast-agent python scripts/build_deploy.py
```

Generated contexts are written under `.build/deploy/`, which is ignored by
Git. Build a single target by naming it:

```bash
uv run --project ../fast-agent python scripts/build_deploy.py researcher
uv run --with huggingface_hub python scripts/deploy_spaces.py researcher --create
```

Never edit files under `.build/`; update the canonical sources in `research/`
or the deployment-specific files in `deploy/`, then rebuild.

### Per-user report archive provisioning

After a caller's private `<username>/research-agent` bucket is verified, the
harness idempotently ensures a private `<username>/research-agent` Space exists.
New Spaces are duplicated from the public template configured by
`RESEARCH_ARCHIVE_TEMPLATE_SPACE` (default:
`evalstate/research-archive-template`) with the bucket mounted read-write at
`/research`.

Both template and duplicate carry `archive-template.json`. The provisioner:

- requires the template marker to match its expected version before duplication
- refuses to modify an existing Space without a valid managed marker
- reports `version_mismatch` without overwriting an older managed installation
- configures the bucket volume atomically during duplication
- retries safely on later requests and does not fail research if optional
  archive provisioning fails

Build and publish the data-free public template with:

```bash
uv run --project ../fast-agent python scripts/build_deploy.py \
  research-archive-template
hf upload <owner>/research-archive-template \
  .build/deploy/research-archive-template \
  --repo-type space
```

The experimental app uses FastMCP's optional Apps dependencies. Run it locally
with the same extra installed by the deployment image:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  python fastmcp_research_app.py
```

### Preview the Prefab UI without MCP or OAuth

Render the real `build_research_ui()` component tree with static sample state
and capture it with local Chrome:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  python scripts/render_app_preview.py --state all
```

HTML and PNG files are written under `.artifacts/app-preview/`. Preview mode
uses Prefab's bundled standalone renderer and disables the app's mount-time MCP
tool calls, so it requires no server, token, OAuth flow, or network access.

Curated design inputs live under `design/references/`: `baseline/` records the
current implementation and `handoff/` contains the target design references.
Generated `.artifacts/` previews are intentionally not design history and are
ignored by Git.

Render the three Hugging Face design-option packs in both light and dark modes:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  --with prefab-ui python scripts/render_design_packs.py
```

Open `.artifacts/prefabtest-packs/index.html` to compare Hub Classic, Spaces
Gradient, and Dataset Studio. These review variants do not change the
production app until one is selected.

Running jobs can be cancelled from the app header. Cancellation is coordinated
through an in-memory task registry, matching the single-process Space
deployment model.

Birch drafts are written under the verified session's `scratch/` directory and
finalized by `finalize_birch_artifact` in a short-lived Hugging Face Sandbox.
The renderer mounts only that bucket session at `/workspace`, copies the
vendored Birch Skill to `/opt/birch`, validates the HTML, and writes the final
artifact under the same session's `output/` directory.

Check host-compatible dark styling with:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  python scripts/render_app_preview.py --state running --mode dark
```

## Verify identity and bucket use

The `research_app.py` harness intercept runs before every agent invocation. It
uses the caller bearer token/OAuth access token to look up the Hugging Face user,
then checks or creates:

```text
<username>/research-agent
```

and writes:

```text
hf://buckets/<username>/research-agent/<session-id>/scratch/.workspace.json
hf://buckets/<username>/research-agent/<session-id>/output/.keep
```

If that setup fails, the harness invocation fails before the LLM is called.
If it succeeds, the verified `root`, `scratch`, and `output` paths are injected
into the prompt and added to request metadata.

The bucket is not a local mount in the normal MCP path. It is a Hugging Face Hub
bucket addressed by `hf://...`; the agent must use the Hugging Face MCP tools to
read/write there.

The production Harness disables model-visible access to the Space host shell and
filesystem. Relative `scratch/` and `output/` artifact paths always refer to the
authenticated bucket session; they are never shared directories under
`/app/research`.
