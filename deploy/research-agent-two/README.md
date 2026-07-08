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
  - read-repos
  - contribute-repos
  - write-repos
  - manage-repos
  - read-mcp
  - jobs
---

# Research Agent Two

Experimental FastMCP App deployment for the fast-agent research agent.

The model-visible `research` entrypoint returns an app immediately. The app
starts the research workflow through app-only backend tools and polls status to
show an ongoing timeline of LLM/tool-loop events.
