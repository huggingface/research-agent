# FastMCP App experiment

This branch adds `fastmcp_research_app.py`, a thin experimental FastMCP App
wrapper around the existing research Harness app.

## Why this looks easy

The research agent already runs through fast-agent's Harness API via
`research/research_app.py`. The FastMCP adapter in `../fast-agent` already maps
Harness requests to MCP/FastMCP context and sets:

```python
RequestParams(
    tool_execution_handler=MCPToolProgressManager(...),
    emit_loop_progress=True,
)
```

That means active calls can emit MCP progress notifications for the LLM/tool
loop without custom research-agent changes.

## Run

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  python fastmcp_research_app.py \
  --host 127.0.0.1 \
  --port 8724
```

The server exposes:

- a FastMCP App provider named `Research Agent`
- `research`, the model-visible UI entry point
- app-only `start_research` and `research_status` backend tools

## Why the runner uses the Harness directly

Short-lived app handlers should normally use
`HarnessMCPAdapter.invoke_agent(ctx=...)`. It is the smallest bridge from a
FastMCP request to fast-agent.

This app deliberately returns a job handle before research finishes. A
background task must not retain the completed tool call's request-scoped
`MCPContext`, so `start_research` captures `AgentAuth` and
`research/research_runner.py` opens an explicit Harness session. The runner is
the protocol-neutral core; job retention, OAuth, tracing, and Prefab rendering
remain separate.

## Observability expected

While a request is active, FastMCP clients with a progress handler should see
messages from fast-agent's loop/tool progress path, e.g. roughly:

```text
research/agent_loop: started
research/agent_loop: step 1 (llm)
research/agent_loop: step 2 (tool ...)
hf/...: started
hf/...: completed
research/agent_loop: completed
```

The app maps these events into a live timeline and polls the bounded in-memory
job store for status and final output.

## Current caveats

- Jobs survive app re-renders only while this server process is alive and for
  24 hours after completion.
- Reopening an expired historical app shows an unavailable state and does not
  launch replacement work.
- The research workspace still requires Hugging Face auth (`HF_TOKEN`, local
  `hf auth login`, or forwarded OAuth/bearer auth) because the existing harness
  wrapper verifies/creates per-user buckets before invoking the LLM.
