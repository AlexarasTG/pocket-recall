# Pocket Recall

Pocket Recall is a local-first memory tool for coding agents. You have complete 
control over what is saved; agents automatically search for relevant knowledge 
and fetch only the records they need. Memories and embeddings stay on your machine.

It provides:

- a `memory` CLI for managing the library;
- an MCP server for any harness that supports local STDIO servers.

## How it works

Pocket Recall separates recall into two steps to limit context use:

1. `search` returns up to five compact candidates.
2. `fetch` returns one selected record in full.

Memory creation is always explicit. Records contain a title, a body of at most
1,000 characters, and aliases. The backend rejects recognizable credentials and
raw JSON payloads.

## Install for development

Requires Python 3.11 or newer with SQLite FTS5.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
memory maintenance init
```

Initialization creates the local databases and downloads the pinned embedding
model. After that, storage, embedding, and retrieval work locally.

An editable install uses the code under `src/` directly. Reinstall only after
changing packaging metadata or console entry points.

## CLI

```sh
memory save --title "Start times" \
  --body "ST means start times." \
  --alias "ST" --alias "start times"

memory search "start times"
memory read MEMORY_ID
memory delete MEMORY_ID
memory restore MEMORY_ID
memory maintenance status
memory maintenance review
```

Run `memory COMMAND --help` for all options. Mutating commands show a preview
and require confirmation.

The first command starts a shared background service automatically. Stop it with
`memory maintenance stop`; otherwise it ends when the laptop shuts down.

## MCP integration

The `pocket-recall-mcp` executable exposes three tools:

- `search(query)`: compact candidates;
- `fetch(id)`: one complete active record;
- `save(title, body, aliases, id?)`: create one record, or fully replace the
  record with `id`.

Any MCP-compatible harness that supports local STDIO servers can launch this
executable. Configure read tools to run automatically and `save` to require
approval.

Claude Code:

```sh
claude mcp add --scope user pocket-recall -- /absolute/path/to/.venv/bin/pocket-recall-mcp
```

Claude Code asks before every MCP call by default. To run reads automatically, allow
`mcp__pocket-recall__search` and `mcp__pocket-recall__fetch` under `permissions.allow`
in `~/.claude/settings.json`.

Codex:

```sh
codex mcp add pocket-recall -- /absolute/path/to/.venv/bin/pocket-recall-mcp
```

Then add the approval policy to `~/.codex/config.toml` and restart Codex:

```toml
[mcp_servers.pocket-recall]
default_tools_approval_mode = "writes"

[mcp_servers.pocket-recall.tools.save]
approval_mode = "prompt"
```

Pi:

```sh
pi mcp add pocket-recall --exposure direct \
  --description "Search, fetch, and save user-approved durable knowledge." \
  -- /absolute/path/to/.venv/bin/pocket-recall-mcp
```

## Worth-remembering skill

[`skills/worth-remembering`](skills/worth-remembering) helps you decide what deserves a memory. Run it at the
end of a work session to get proposals for small, durable records. Run it with `review` about once a week to
"dream": it reads `memory maintenance review`, asks about frequent searches with no results, and proposes merges,
splits, or cleanups. It only proposes; nothing is saved without your approval.

## Local data

Pocket Recall stores private application data under:

```text
~/.local/share/pocket-recall/
├── memory.sqlite         authoritative records and recoverable versions
├── search-index.sqlite   rebuildable lexical and vector index
├── audit.sqlite          compact retrieval measurements
├── models/               local embedding model
└── snapshots/            seven recent daily memory snapshots
```

Deleted and replaced versions remain recoverable for 60 days. Retrieval audit
events contain no memory bodies and expire after 90 days.

## Project structure

```text
src/pocket_recall/
├── storage/      authoritative, search, audit, and snapshot persistence
├── retrieval/    indexing and result selection
├── embeddings/   local model configuration and lifecycle
├── transport/    shared service, client, and protocol
├── mcp/          harness-neutral MCP adapter
└── cli.py        human-facing command line
```

Development rules and architectural gotchas are in [`AGENTS.md`](AGENTS.md).

## Development checks

```sh
scripts/build.sh
```

It refreshes the editable install, compiles, formats with isort and black, runs the
tests and `pip check`, then stops the shared service so the next command starts
it with the current code.
