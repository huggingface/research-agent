---
title: Research Agent Two
emoji: 🔎
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
hf_oauth: true
hf_oauth_expiration_minutes: 480
hf_oauth_scopes:
  - inference-api
  - read-mcp
  - write-repos
  - manage-repos
---

# Research Agent Two

Experimental FastMCP App deployment for the fast-agent research agent.

The model-visible `research` entrypoint returns an app immediately. The app
starts the research workflow through app-only backend tools and polls status to
show an ongoing timeline of LLM/tool-loop events.

## Private session archive

The preferred Space configuration is a private bucket volume:

```bash
hf spaces volumes set evalstate/research-agent-two \
  -v hf://buckets/evalstate/research-sessions-private:/app/research/sessions
```

FastAgent then writes raw session histories and `research-traces/` Codex exports
directly to the private bucket. No archive token is present in the application
environment.

For deployments where a bucket volume is unavailable, configure the fallback
explicit archiver with these Space settings:

- Variable:

  ```text
  RESEARCH_ARCHIVE_HF_URL=hf://buckets/<owner>/<private-bucket>
  ```

- Secret:

  ```text
  RESEARCH_ARCHIVE_TOKEN=hf_...
  ```

Create a dedicated fine-grained token with write access only to that bucket.
Do not use a personal broad-scope token. The archive credential is passed
directly to `HfApi` and `HfFileSystem`; it is never assigned to `HF_TOKEN`,
forwarded to MCP, or placed in model-visible context.

The app creates a missing archive bucket as private and refuses to upload to an
existing public bucket. Each job archives:

```text
<session-id>/session.json
<session-id>/history_research*.json
research-traces/<session-id>/<session-id>__research__codex.jsonl
```
