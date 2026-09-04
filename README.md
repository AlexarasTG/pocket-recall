# Pocket Recall

A general-purpose, local-first memory tool: explicit user-controlled writes,
compact search results, and selective full-record recall. No dependency on an
agent harness.

The distribution is `pocket-recall`, the Python package is `pocket_recall`,
and the terminal command is `memory`.

## Components

- `models.py`: editable drafts, authoritative records, and compact candidates.
- `config.py`: storage paths and limits; no implicit filesystem writes.
- `service.py`: mutation, listing, recovery, search, and fetch contracts.
- `storage/memory_store.py`: record storage and pending search-index updates.
- `storage/archived_memory_store.py`: archived versions and recovery expiry dates.
- `storage/database.py`: database initialization and transactions.
- `storage/search_store.py`: SQLite search-index storage and queries that find matching records.
- `storage/retrieval_audit_store.py`: compact retrieval measurements and their retention limits.
- `storage/database_snapshot_manager.py`: daily canonical snapshots and database restoration.
- `retrieval/index_synchronizer.py`: apply pending changes and rebuild derived search data.
- `retrieval/search_coordinator.py`: decides which matching method to try and builds short search results.
- `retrieval/search_text_processing.py`: query normalization, spelling checks, and excerpt selection.
- `embeddings/embedding_provider.py`: local model loading, input checks, and normalized vectors.
- `embeddings/model_lifecycle_manager.py`: lazy model loading, shared use within the core, and idle unloading.
- `embeddings/model_specification.py`: model name, repository, pinned revision, dimensions, token limit, and query instruction.
- `transport/pocket_recall_service.py`: shared storage/model access, concurrent socket requests, logging, and index retries.
- `transport/pocket_recall_client.py`: Pocket Recall operations, one-request socket calls, and automatic service startup.
- `transport/operation_dispatcher.py`: explicit internal operations mapped to the core.
- `transport/service_protocol.py`: versioned newline-delimited JSON messages.
- `validation.py`: body-length and obvious-secret checks.
- `cli.py`: terminal commands, previews, and confirmation.
- `pi-extension/`: optional Pi integration for workspace-gated recall and `/remember_this`.

Pocket Recall keeps one private local library in `~/.local/share/pocket-recall/`.
No developer or company workspace is built into the package. Empty workspace
allowlists disable automatic client activation.

Model-specific facts stay together in `embeddings/model_specification.py`;
adjustable settings such as thresholds, thread counts, and timeouts live in `config.py`.

## Pi extension

The optional TypeScript package under [`pi-extension/`](pi-extension/) exposes
compact search/fetch tools and the explicitly approved `/remember_this` flow.
See its README for configuration and development loading instructions.

## Terminal usage

Requires Python 3.11 or newer with SQLite FTS5 support and the package dependencies.
Install in a virtual environment from the project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/memory maintenance init
.venv/bin/memory save \
  --title "Example concept" --body "A short explanation." --alias "EC"
```

Installing the package also provides the `memory` command. `maintenance init` is
explicit, safe to repeat, and prepares the local databases and model.
`maintenance reindex` can recreate a missing search index. Other commands do not
create missing databases.

For development, include the formatting tools:

```sh
.venv/bin/python -m pip install -e ".[dev]"
```

The editable install uses the code in `src/` directly; source edits do not need
another install. In Zed, use `toolchain: select` and choose this project's
`.venv/bin/python` so import checking uses the installed dependencies.

Initialization downloads the pinned FastEmbed model into the library's `models/`
directory if needed. Subsequent embedding and search use local files only. No
memory text is sent to an external service. ONNX Runtime and Hugging Face telemetry
are disabled before this tool imports them. Hosts that import those libraries
earlier should set `ORT_DISABLE_TELEMETRY=1` and `HF_HUB_DISABLE_TELEMETRY=1` before
starting Python.
The early opt-out follows [ONNX Runtime's privacy guidance](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md).

Everyday commands:

- `save [ID] [--title TEXT] [--body TEXT] [--alias TEXT ... | --clear-aliases]`
- `read [ID] [--deleted | --history | --revision REVISION_ID] [--limit NUMBER] [--offset NUMBER]`
- `search "FOCUSED QUERY"`
- `delete ID`
- `restore ID [--revision REVISION_ID]`

Maintenance commands:

- `maintenance init`
- `maintenance status`
- `maintenance reindex`
- `maintenance restore YYYY-MM-DD`
- `maintenance stop`

Commands connect to one background service over an owner-only Unix socket. The
first command starts it automatically; laptop shutdown or `maintenance stop`
ends it. The next command starts it again. The service is the only runtime
gateway to the library, while `memory.sqlite` remains authoritative.

`save` without an ID creates a memory and requires a title and body. `save ID`
updates that exact memory; an unknown or deleted ID fails instead of creating
one. Its preview clearly identifies Create or Update. `--clear-aliases` requires
an existing ID.

`read` lists summaries without bodies. `read ID` returns one full current memory.
`read --deleted` lists deleted summaries, and `read ID --deleted` reads one deleted
memory in full. `read ID --history` lists archived-version summaries and expiry
dates; `read ID --revision REVISION_ID` reads the selected archived version in full.
The three selection flags cannot be combined. History and revision selection
require a memory ID. Pagination applies only to listings (default limit 50,
offset 0); passing pagination flags when reading one version is an error.

Use `--body-file PATH` instead of `--body` to read UTF-8 text. Creating, updating,
deleting, and restoring all show a preview and require typing `yes`; there is
no confirmation-bypass flag. Updates preserve fields not supplied. Passing
`--alias` replaces the alias list. If another session changes a previewed record,
the command refuses the write and asks you to read it again.

Bodies are limited to 1,000 Unicode code points, including whitespace. Content
is never truncated. Validation rejects recognizable credential formats and
whole JSON objects/arrays as raw payloads. This is a conservative check, not a
guarantee that every secret or production payload can be identified. Store
curated explanations, not credentials or raw logs. Detection may also reject
examples that look like credential assignments. The Bearer/Basic check ignores
alphabetic-only values so ordinary authentication descriptions are accepted;
alphabetic-only credentials can therefore pass this check too.

Deleted records and older versions are recoverable for 60 days. `read ID --history` shows
revision IDs and expiry dates. Restoration preserves the memory ID and creation
date, refreshes the update date, and retains the displaced version. Expired
recovery data is hidden immediately and removed during subsequent approved
writes; it cannot be restored through the application.

Before the first saved-memory change of each local calendar day, Pocket Recall
stores a validated copy of `memory.sqlite` under `snapshots/`. It keeps the seven
newest daily snapshots. Snapshot failure does not block the memory change, but it
is reported as a warning. `maintenance restore YYYY-MM-DD` stops the service,
validates and restores that snapshot, preserves the previous database as
`memory-before-restore.sqlite`, rebuilds the search index, and leaves the service
stopped. The next normal command starts it again.

Saving a memory and marking its search-index update as pending is one database
transaction. Indexing is attempted immediately afterward. A failed index update
does not undo the save; its pending request remains durable. Keyword and vector
changes commit together. A failed embedding leaves the new version readable by
ID but not searchable until indexing succeeds; outdated indexed versions are excluded.
`maintenance status` reports
whether the index is up to date, checking both queued updates and missing or stale
indexed records. It also reports the retrieval-audit file size, event count, and
oldest/newest event dates. `maintenance reindex` rebuilds the disposable
index from current active records without changing their content or timestamps.
The `read` command reads saved records, not the search index.

Successful searches and full-record fetches add compact rows to `audit.sqlite`.
Search rows contain the query, returned IDs, match kinds and scores, character
count, and duration; fetch rows contain the selected ID and response measurements.
Memory content is not copied into this database. Events expire after 30 days, and
the database is trimmed from 10 MB toward 8 MB when necessary. Audit-write failure
is logged and never blocks retrieval.

Search tries whole title/alias matches first, ignoring case and extra whitespace.
If any exist, only that tier is returned. Otherwise, all query words must match
across the title, aliases, or body, allowing English word variations through
stemming. Titles and aliases have equal ranking weight above body text. Ties
use memory ID, so ordering is repeatable. Scores rank within a tier, not factual
confidence, and should not be compared between different queries.

By default, semantic search runs only when exact, keyword, and typo searches
return nothing. It compares one vector per memory, built from its title, aliases,
and body. IDs and dates are excluded. The default cosine-similarity cutoff is
0.85; this is a provisional relevance filter, not an 85% confidence estimate.
Semantic excerpts use the opening of the body.

To experiment without changing saved data or rebuilding the index:

```sh
memory search "recording interval" \
  --semantic-policy fill_remaining_slots --similarity-threshold 0.85
```

`fill_remaining_slots` keeps the existing exact/keyword/typo candidates first, then appends
qualifying semantic matches with different IDs, up to the same five-result cap.
The default policy is `on_zero_results`. Both settings are also available through
`MemoryConfig`. A model failure is reported as an error, not an empty semantic search.

If keyword search finds nothing, spelling fallback allows one inserted, removed,
replaced, or adjacent-swapped character per alphabetic word of at least five
characters. Both spellings must meet that minimum; short acronyms and numeric
identifiers remain strict. At most eight alternatives per word are considered,
in alphabetical order. Prefix expansion is disabled; intentional abbreviations
belong in aliases. Punctuation separates keyword terms; quotes and words such as
`OR` are literal input, not a query language. Queries are limited to 1,000
characters and 32 distinct words.

Search returns JSON with `candidates` and `index_update_pending`, not full records.
Up to five candidates include a match kind (`exact`, `lexical`, `typo`, or `semantic`), score,
and an excerpt of at most 160 characters including ellipses. Excerpts surround
the first body match, or use the opening when only a title/alias matched. Use
`read ID` to fetch a selected record. Pending indexing produces an incomplete-results
warning; unreadable indexes produce errors rather than empty matches. Results
exclude deleted records and indexed versions that no longer match canonical storage.

## Local embeddings

FastEmbed runs `BAAI/bge-small-en-v1.5` on CPU, with two inference threads by
default (`embedding_threads`). Each normalized vector contains 384 float32 values.
Vectors stay in SQLite; NumPy compares current vectors in bounded batches, with
no separate vector database or SQLite extension required.

Index metadata records the provider/runtime versions, model revision, dimensions,
and text/vector format. Incompatible metadata requires `maintenance reindex`;
`maintenance init` can upgrade the older keyword-only index and rebuild it.
Rebuilds leave memory content, timestamps, and archived versions unchanged.

The model accepts at most 512 tokens per embedding input, including the title
and aliases or the query's retrieval instruction. Inputs exceeding that limit
raise an embedding error instead of silently truncating text. This does not
change the 1,000-character storage limit; an approved memory remains saved with
indexing pending if its combined input cannot be embedded.

The daemon's one `MemoryStore` shares one lazy model between indexing and search
for every client. It unloads after 60 minutes without model use
(`model_idle_timeout_minutes`), using an idle timer rather than polling. Direct
reads, status, and successful lexical searches do not load it.

Each socket connection carries one versioned JSON request and response. The
service handles at most 16 requests concurrently and rejects requests over 64 KB.
Failed index updates stay durable and receive four in-memory retries after 5
seconds, 30 seconds, 2 minutes, and 10 minutes. A restart tries pending work
again; `maintenance reindex` remains the manual recovery path.

Minimal rotating service logs live beside the databases as `service.log` plus
two 1 MB backups. They record request IDs, operation names, lifecycle events,
and failures—not memory content, aliases, queries, or results.

New database directories are created with owner-only access where supported,
and database files with owner read/write access. Existing directory permissions
are left unchanged. The database is not encrypted; choose a private local path.
