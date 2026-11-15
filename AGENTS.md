# Pocket Recall development guide

## Product boundaries

- Pocket Recall is general-purpose and agent-neutral.
- Memory writes require explicit user intent and approval. Never create, edit,
  merge, deduplicate, or delete memories automatically.
- Recall is automatic but conservative. We prefer a missed result over irrelevant
  context.
- Search returns compact candidates. Full bodies enter agent context only
  through a selected fetch, except when a short body fits in the bounded excerpt.
- Stored memory is dated evidence, not truth. Surface conflicts with current code
  or runtime evidence; never resolve them by silently changing a record.
- Do not add taxonomy, scope fields, graph relationships, or cleanup automation
  without evidence from real usage.

## Architecture

- `memory.sqlite` is authoritative. `search-index.sqlite` and `audit.sqlite` are
  disposable and must never become alternative sources of truth.
- The shared local service is the only runtime gateway to the library. CLI and
  agent adapters use `PocketRecallClient`; adapters must not access SQLite or the
  embedding model directly.
- Keep MCP and Pi thin. Business validation, storage rules, retrieval policy,
  and indexing belong in the Python backend.
- Workspace activation belongs to an adapter's configuration, not the storage
  schema or retrieval ranking.
- Keep canonical records independent of model and index formats. Changing the
  embedding model must require rebuilding only the search index.

## Important behavior

- Saving canonical state and its pending index update is one transaction.
  Indexing happens immediately afterward. A failed index update must not lose an
  approved memory; it remains pending and outdated indexed versions stay hidden.
- An unreadable index is an error, not an empty search result. A legitimate
  no-match search is successful.
- Acronyms and identifiers depend on exact/lexical retrieval. Semantic similarity
  is a relevance filter, not factual confidence. Tune thresholds from real
  records and audit evidence, not synthetic data.
- Embedding imports are intentionally deferred so model loading stays lazy and
  telemetry opt-outs are set before ONNX Runtime and Hugging Face are imported.
- One daemon owns the stores and lazy model instance for all clients. Direct
  reads and successful lexical searches should not load the model.
- Deletes are soft. Deleted and displaced versions remain outside search and are
  recoverable for 60 days.
- Only `memory.sqlite` is snapshotted. Search and audit databases are rebuildable.
- Retrieval auditing must not copy titles, aliases, excerpts, bodies, requests,
  or conversations. Audit failure must never block retrieval.

## Data and compatibility

- Record bodies are limited to 1,000 Unicode code points and are never truncated.
- Current candidate excerpts are limited to 160 characters and search results to
  five records. Treat these and retrieval thresholds as configurable policy.
- The internal service uses versioned newline-delimited JSON over an owner-only
  Unix socket. Preserve protocol compatibility or version it explicitly.
- Keep credentials, secrets, private keys, and raw production payloads out of
  memories. Backend validation is authoritative but cannot detect every secret.
- Normal operation must remain offline after dependency and model setup.

## Working in this repository

- Prefer simple names and plain docstrings that explain purpose and responsibility.
- Keep adjustable behavior in `config.py`; keep fixed model identity and format
  details in `embeddings/model_specification.py`.
- Do not duplicate backend validation in adapters. Boundary shape validation is
  still required for socket and MCP messages.
- Use temporary libraries and model stubs for destructive or synthetic checks.
  Never populate the user's real memory library with test data.
- Do not introduce a taxonomy, vector database, scheduler, fallback database
  access, or extra agent tools without a demonstrated need.

Run before committing:

```sh
scripts/build.sh
```

It refreshes the editable install, compiles, formats with isort and black, runs the
tests and `pip check`, then stops the shared service so the next command starts
it with the current code.
