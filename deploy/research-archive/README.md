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

When a run contains a completed private Open Knowledge Format bundle at
`output/okf/`, the archive exposes an Evidence tab and downloadable
`output/okf.zip`. Validation is local and bounded: the archive checks OKF
frontmatter, trust and lifecycle fields, source/citation joins, canonical
report-link coverage, and the completion manifest's bundle digest. Source URLs
are displayed but never fetched, and no executor, attester, script, or HTML
from a bundle is run.

OKF artifacts remain private by default and are deliberately excluded from the
public report mirror.
