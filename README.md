# Memory Manager

A general-purpose, local-first memory tool: explicit user-controlled writes,
compact search results, and selective full-record recall. No dependency on an
agent harness.

## Components

- `models.py`: editable drafts, authoritative records, and compact candidates.
- `config.py`: storage paths and limits; no implicit filesystem writes.
- `service.py`: mutation, listing, recovery, search, and fetch contracts.
- `memory_store.py`: record storage and pending search-index updates.
- `memory_archive_store.py`: archived versions and recovery expiry dates.
- `database.py`: database initialization and transactions.
- `validation.py`: body-length and obvious-secret checks.
- `cli.py`: terminal commands, previews, and confirmation.

Data-directory and workspace paths are explicit configuration. No developer
home directory or company workspace is built into the package. Empty workspace
allowlists disable automatic client activation.

## Terminal usage

Requires Python 3.11 or newer. The CLI uses only the standard library.
Run from the project directory without installing dependencies:

```sh
PYTHONPATH=src python3 -m memory_manager --data-dir /path/to/private/library init
PYTHONPATH=src python3 -m memory_manager --data-dir /path/to/private/library create \
  --title "Example concept" --body "A short explanation." --alias "EC"
```

Installing the package also provides the `memory` command. Every command takes
`--data-dir` before the command name. `init` is explicit and safe to repeat;
other commands do not create missing databases.

Commands:

- `create --title TEXT --body TEXT [--alias TEXT ...]`
- `list [--deleted] [--limit NUMBER] [--offset NUMBER]`
- `show ID [--deleted | --revision REVISION_ID]`
- `update ID [--title TEXT] [--body TEXT] [--alias TEXT ... | --clear-aliases]`
- `delete ID`
- `history ID [--limit NUMBER] [--offset NUMBER]`
- `restore ID [--revision REVISION_ID]`
- `status`

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

Deleted records and older versions are recoverable for 60 days. `history` shows
revision IDs and expiry dates. Restoration preserves the memory ID and creation
date, refreshes the update date, and retains the displaced version. Expired
recovery data is hidden immediately and removed during subsequent approved
writes; it cannot be restored through the application.

Saving a memory and marking its search-index update as pending is one database
transaction. The CLI reports these states separately. `status` counts pending
updates; a count of zero alone does not prove a search index exists. Direct
`show` and `list` read saved records, not the search index.

New database directories are created with owner-only access where supported,
and database files with owner read/write access. Existing directory permissions
are left unchanged. The database is not encrypted; choose a private local path.
