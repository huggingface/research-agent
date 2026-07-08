# Recipe: PR change writeup

Use when explaining a change set to reviewers, release owners, or maintainers.

## Required source checks

- Inspect changed files and tests before summarizing.
- Identify user-visible behavior, internal refactors, migrations, and compatibility impact.
- Separate confirmed behavior from intended behavior when tests are absent.
- Capture rollout, rollback, and open questions if the source mentions them or they are necessary for safe review.

## Recommended structure

1. Reviewer-oriented summary: what changed and why it matters.
2. Before/after behavior using source evidence.
3. File-by-file tour ordered by comprehension, not alphabetically by default.
4. Tests and evidence.
5. Rollout, rollback, risks, and open questions.

## Birch primitives to use

- `.section`, `.section-head`, `.split`, `.reference-panel` for narrative plus review notes.
- `.card` for changed areas or files.
- `.diff` and `.code-block` for representative excerpts.
- `.timeline` for rollout chronology only when timing matters.
- `.checklist` for reviewer actions and verification.

## Avoid

- Restating the diff mechanically without explaining behavior.
- Omitting tests or verification status.
- Mixing assumptions with confirmed changes.
- Overloading the first viewport with file trivia instead of review value.

## Validation checklist

- A reviewer can tell what changed, why, and where to inspect first.
- Before/after is explicit for behavior changes.
- Test evidence or missing-test caveat is present.
- Rollout/rollback implications are covered when relevant.
