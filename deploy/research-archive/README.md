---
title: Research Archive
emoji: 🗂️
colorFrom: yellow
colorTo: purple
sdk: docker
app_port: 7860
---

# Research Archive

Private browser for Research Dispatch workspaces stored in the mounted
`evalstate/research-agent` bucket. The bucket is mounted read-write so reports
can be permanently deleted from the archive after explicit confirmation.

`archive-template.json` identifies this as a managed Research Archive and
records the installed template version. Provisioning copies this marker from
the public template so future upgrades can detect version mismatches before
changing application files or volume configuration.
