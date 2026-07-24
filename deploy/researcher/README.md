---
title: Hugging Face Researcher
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
  - jobs
  - contribute-repos
  - write-repos
  - manage-repos
---

# Hugging Face Researcher

FastMCP App deployment for the Hugging Face Researcher.

The model-visible `researcher` entrypoint returns an app immediately. The app
starts the research workflow through app-only backend tools and polls status to
show an ongoing timeline of LLM/tool-loop events.
