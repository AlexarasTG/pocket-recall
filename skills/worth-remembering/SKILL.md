---
name: worth-remembering
description: Propose minimal, durable Pocket Recall memory changes. Default mode captures knowledge from the current work session; `review` mode checks the library for search gaps and merge, split, or cleanup candidates. Proposes only; writes require explicit approval.
disable-model-invocation: true
---

# Worth remembering

Ask: **What small piece of stable knowledge about how this company, project, or codebase works would have helped us reach the right answer faster?**

## Mode

- No argument: follow [references/session.md](references/session.md).
- `review`: follow [references/review.md](references/review.md).

Read only the selected reference.

## Select

- Extract durable concepts, responsibilities, relationships, or conventions—not a session summary.
- Prefer facts likely to remain useful across future tasks, not details that may be stale tomorrow.
- Exclude temporary bugs, current configuration values, branch details, example IDs, logs, task progress, and implementation plans.
- Exclude ticket IDs, task names, and work tracking. Pocket Recall is not an issue tracker.
- Use verified facts. Do not turn a single observation, inference, or tentative agreement into an architectural rule.
- Apply a strict value-to-context-cost test. No change is a valid outcome. Do not fill a quota or preserve everything learned.

## Draft

- One narrowly scoped concept per record. Keep related but independently useful concepts separate.
- Use the shortest self-contained wording that preserves the important distinction. Bodies are limited to 1,000 characters.
- No introductory padding, repeated ownership statements, investigation history, or adjacent-system explanations.
- Use a short title and only useful search aliases: exact identifiers and meaningful alternative names, not redundant prose.
- Present the exact proposed title, aliases, and body. For a revision, show the current record next to it. Keep rationale outside the record and brief.
- Respect rejected topics and wording; do not reintroduce them as extra context.

## Approval and saving

- Invoking this skill authorizes recommendations, not memory writes.
- Wait for explicit approval. Save only approved records, with the approved wording verbatim.
- Create with `save(title, body, aliases)`. Revise with `save(title, body, aliases, id)`: fetch the record first and send the complete revised record. Never create a duplicate instead of revising.
- Never delete. List `memory delete ID` commands for the user to run. Never pipe confirmation into the `memory` CLI.
- After saving, confirm the titles briefly. If nothing changed, say so.
