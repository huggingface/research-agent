---
title: Research Archive Template
emoji: 🗂️
colorFrom: yellow
colorTo: purple
sdk: docker
app_port: 7860
---

# Research Archive Template

Public, data-free template for private per-user Researcher archive Spaces.
Provisioning duplicates this repository into the caller's namespace and mounts
their private `research-agent` bucket at `/research`.

The copied `archive-template.json` file is the authoritative template version
marker used to detect managed Spaces and future version mismatches.
