# Review mode

Run weekly. The input is `memory maintenance review`, which returns a bounded list of candidates. Never list or read the whole library.

Fetch only the records you are judging, with `fetch` or `memory read ID`.

## Sections

- `gaps`: query keywords that agents searched with no results. Drop generic words, ticket IDs, and task names. For each remaining keyword, ask the user one short question about what it means. Draft only from the answer; never invent content.
- `similar_pairs`: semantically close records, not confirmed duplicates. Fetch both. Propose a merge only when they describe one concept. Otherwise propose sharper titles or aliases, or no change.
- `oversized`: bodies near the limit. Propose a split only when the record holds independently useful concepts.
- `unused`: never returned by search since `unused_since`. Propose deletion only when the record is stale or wrong. If agents likely searched with different words, propose better aliases instead. Otherwise keep it.

## Output

One numbered list grouped by section. Each item: action, record IDs, exact proposed records, one-line rationale. Then wait for approval.
