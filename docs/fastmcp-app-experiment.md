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
uv run --project ../fast-agent python fastmcp_research_app.py \
  --host 127.0.0.1 \
  --port 8724
```

For per-request isolation:

```bash
uv run --project ../fast-agent python fastmcp_research_app.py --session-scope request
```

The server exposes:

- a FastMCP App provider named `Research Agent`
- `open_research` UI entry-point tool
- `continue_research` app/backend tool
- a plain `research` MCP tool for clients that do not render MCP Apps yet

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

This is sufficient for a basic activity indicator or timeline. Rich structured
UI state would need one additional mapping layer because MCP progress
notifications are primarily `(progress, total, message)`.

## Current caveats

- Progress only streams while the MCP tool call is active.
- Long-running/background research should use explicit job handles or FastMCP
  tasks rather than relying on one active call.
- The placeholder UI response is a simple dict. A real Apps UI can project the
  returned `AgentResponse` into a richer component without changing the agent.
- The research workspace still requires Hugging Face auth (`HF_TOKEN`, local
  `hf auth login`, or forwarded OAuth/bearer auth) because the existing harness
  wrapper verifies/creates per-user buckets before invoking the LLM.

## Effort estimate

- Basic FastMCP App wrapper: low; this branch is the prototype.
- Observable LLM/tool loop progress: already wired by `HarnessMCPAdapter`.
- Polished app UI/timeline: moderate; mostly component rendering and event
  shaping, not core agent plumbing.
- Durable async research jobs: moderate; add start/status/result tools or use
  FastMCP task support.
