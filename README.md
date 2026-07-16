# research-agent

A small `fast-agent` research home for a Hugging Face research agent.

## What is configured

- `research/fast-agent.yaml` is the local fast-agent home.
- The MCP target `hf` connects to `https://huggingface.co/mcp`.
- `research/agent-cards/research.md` lets you publish/run the same agent
  declaratively.
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
        AppOpenRequest(session_id=job.id, agent="research")
    ) as session:
        response = await session.invoke(
            AgentRequest.text(
                job.topic,
                agent="research",
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

For an ordinary MCP App call that completes before its tool call returns, use
`HarnessMCPAdapter.invoke_agent(ctx=...)`; it handles MCP auth, progress, and
session translation. This example uses the explicit Harness API because the
research job continues after `start_research` returns, so it must not retain a
request-scoped FastMCP `Context`.

## Deployment bundles

Python implementation files in `deploy/` are generated copies. After changing
canonical sources, update and verify them with:

```bash
python scripts/sync_deploy.py
python scripts/sync_deploy.py --check
```

The experimental app uses FastMCP's optional Apps dependencies. Run it locally
with the same extra installed by the deployment image:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  python fastmcp_research_app.py
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
