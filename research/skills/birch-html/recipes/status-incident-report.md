# Recipe: Status or incident report

Use for current status updates, outage summaries, recovery reports, and incident follow-ups.

## Required source checks

- Determine current state, impact, duration, affected surfaces, severity, and risk.
- Capture what is confirmed, what is suspected, and confidence in root cause.
- Extract timeline events with times and sources when available.
- Separate completed actions, in-progress work, next actions, and follow-ups.

## Recommended structure

1. First viewport: current state, impact, duration, and severity.
2. Impact and customer/system surfaces.
3. Timeline with canonical timeline classes.
4. Root cause confidence and contributing factors.
5. Actions by state and follow-up owners.

## Birch primitives to use

- `.stat-card`, `.stat-value` for state, duration, impact, and scope.
- `.timeline`, `.timeline-item`, `.timeline-time`, `.timeline-body` for chronology.
- `.badge` with `data-tone="danger|warning|success|info"` for severity and action state.
- `.callout`, `.checklist`, `.plain-list` for summary, mitigations, and follow-ups.
- `.numeric-table` for action/status tables.

## Avoid

- Hiding current state below historical details.
- Overstating root cause confidence.
- Mixing mitigations with permanent fixes.
- Missing follow-up owners or verification criteria when they are known.

## Validation checklist

- Current state is visible immediately.
- Impact, duration, surfaces, and risk are explicit.
- Timeline events use clear times or marked unknowns.
- Root cause confidence is labeled.
- Actions are grouped by done, active, next, and follow-up where applicable.
