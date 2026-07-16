# Recipe: Flow diagram

Use when the artifact needs a compact visual overview of a process, system path, decision sequence, or lifecycle.

## Required source checks

- Identify nodes, decisions, inputs, outputs, terminal states, and exceptional paths.
- Decide whether a diagram is necessary; use HTML steps when a list is clearer.
- Keep labels short and preserve source terms for important states.
- Verify edge direction and decision outcomes against the source.

## Recommended structure

1. Short summary of what the flow explains.
2. Compact inline SVG overview wrapped in `.panel` or `.card`.
3. Details below the diagram as `.flow-list` steps or a table.
4. Caveats for omitted branches or inferred paths.

For module/runtime explainers, use the diagram to show the transformation from
input to output ("request to response", "files to report", "event to side
effect"). Keep source citations in the caption and put longer details in the
HTML flow/list below the SVG.

## Birch primitives to use

- `svg.flow` or `svg.flowchart` for inline diagrams.
- `.flow-node` and `.flow-edge` for diagram nodes and connectors.
- `.panel` or `.card` as the containing surface.
- `.flow-list` for detailed step explanations.

## Avoid

- More than 5-7 visible nodes in the main SVG.
- Wide landscape diagrams unless the source truly requires one.
- Edges that stop in the middle of nodes or miss decision vertices.
- Multi-line labels beyond a title plus one short detail line.
- Porting unsupported diagram-specific classes.

## Validation checklist

- Diagram is portrait or near-square when possible.
- Nodes sit on a simple grid and edges terminate at boundaries.
- Decision branches route to actual decision vertices.
- Larger flows use an overview plus HTML details.
- Mobile readability is checked.
