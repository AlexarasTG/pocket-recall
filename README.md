# Memory Manager

A general-purpose, local-first memory tool: explicit user-controlled writes,
compact search results, and selective full-record recall. No dependency on an
agent harness.

## Components

- `models.py`: editable drafts, authoritative records, and compact candidates.
- `config.py`: storage paths and limits; no implicit filesystem writes.
- `service.py`: mutation, listing, recovery, search, and fetch contracts.
- `memory_store.py`: record storage and pending search-index updates.
- `archived_memory_store.py`: archived versions and recovery expiry dates.
- `database.py`: database initialization and transactions.
- `search_store.py`: SQLite search-index storage and queries that find matching records.
- `index_synchronizer.py`: apply pending changes and rebuild derived search data.
- `search_coordinator.py`: decides which matching method to try and builds short search results.
- `search_text_processing.py`: query normalization, spelling checks, and excerpt selection.
- `validation.py`: body-length and obvious-secret checks.
- `cli.py`: terminal commands, previews, and confirmation.

Data-directory and workspace paths are explicit configuration. No developer
home directory or company workspace is built into the package. Empty workspace
allowlists disable automatic client activation.

## Terminal usage

Requires Python 3.11 or newer with SQLite FTS5 support. The CLI uses only the standard library.
Run from the project directory without installing dependencies:

```sh
PYTHONPATH=src python3 -m memory_manager --data-dir /path/to/private/library maintenance init
PYTHONPATH=src python3 -m memory_manager --data-dir /path/to/private/library save \
  --title "Example concept" --body "A short explanation." --alias "EC"
```

Installing the package also provides the `memory` command. Every command takes
`--data-dir` before the command name. `maintenance init` is explicit and safe to
repeat; `maintenance reindex` can recreate a missing search index. Other commands
do not create missing databases.

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
examples that look like credential assignments.

Deleted records and older versions are recoverable for 60 days. `read ID --history` shows
revision IDs and expiry dates. Restoration preserves the memory ID and creation
date, refreshes the update date, and retains the displaced version. Expired
recovery data is hidden immediately and removed during subsequent approved
writes; it cannot be restored through the application.

Saving a memory and marking its search-index update as pending is one database
transaction. Indexing is attempted immediately afterward. A failed index update
does not undo the save; its pending request remains durable. `maintenance status` reports
pending requests and checks index completeness. `maintenance reindex` rebuilds the disposable
index from current active records without changing their content or timestamps.
The `read` command reads saved records, not the search index.

Search tries whole title/alias matches first, ignoring case and extra whitespace.
If any exist, only that tier is returned. Otherwise, all query words must match
across the title, aliases, or body, allowing English word variations through
stemming. Titles and aliases have equal ranking weight above body text. Ties
use memory ID, so ordering is repeatable. Scores rank within a tier, not factual
confidence, and should not be compared between different queries.

If keyword search finds nothing, spelling fallback allows one inserted, removed,
replaced, or adjacent-swapped character per alphabetic word of at least five
characters. Both spellings must meet that minimum; short acronyms and numeric
identifiers remain strict. At most eight alternatives per word are considered,
in alphabetical order. Prefix expansion is disabled; intentional abbreviations
belong in aliases. Punctuation separates keyword terms; quotes and words such as
`OR` are literal input, not a query language. Queries are limited to 1,000
characters and 32 distinct words.

Search returns JSON with `candidates` and `index_update_pending`, not full records.
Up to five candidates include a match kind (`exact`, `lexical`, or `typo`), score,
and an excerpt of at most 160 characters including ellipses. Excerpts surround
the first body match, or use the opening when only a title/alias matched. Use
`read ID` to fetch a selected record. Pending indexing produces an incomplete-results
warning; unreadable indexes produce errors rather than empty matches. Results
exclude deleted records and indexed versions that no longer match canonical storage.

New database directories are created with owner-only access where supported,
and database files with owner read/write access. Existing directory permissions
are left unchanged. The database is not encrypted; choose a private local path.
