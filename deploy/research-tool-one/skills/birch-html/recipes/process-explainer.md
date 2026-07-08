# Recipe: Process explainer

Use when explaining an operational, business, product, support, deployment, or human/system workflow.

## Required source checks

- Identify actors, systems, inputs, outputs, triggers, handoffs, and terminal states.
- Separate documented behavior from inferred behavior.
- Capture decision points, failure modes, retries, escalations, and operator actions.
- Preserve source terms for states and roles when they matter.

## Recommended structure

1. One-paragraph mental model and scope.
2. Actor/system inventory.
3. Lifecycle as ordered steps.
4. Decision points and failure modes.
5. Operator checklist and caveats.

## Birch primitives to use

- `.flow-list`, `.flow-step`, `.flow-num`, `.flow-title`, `.flow-detail` for lifecycle steps.
- `.timeline` when explaining actual chronology.
- `.checklist` for operator actions.
- `.callout` for assumptions, warnings, or source gaps.

## Avoid

- Collapsing decisions into a single vague step.
- Omitting who owns each handoff.
- Drawing wide diagrams when HTML steps are clearer.
- Mixing ideal process with observed process without labels.

## Validation checklist

- Actors and systems are named.
- Lifecycle has clear start/end conditions.
- Decision points and failure modes are visible.
- Operator checklist is actionable.
- Documented vs inferred content is labeled.
