---
title: Research Tool One
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

# Research Tool One

A fast-agent MCP server for Hugging Face ecosystem research.

The server requires Hugging Face authorization and forwards the caller token to
Hugging Face Inference Providers and the Hugging Face MCP server. It creates or
uses a per-user private bucket at `<username>/research-agent` for research
outputs.
