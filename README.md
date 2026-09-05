# Pocket Recall

Pocket Recall is a local-first memory tool for coding agents. You choose what is
saved; agents automatically search for relevant knowledge and fetch only the
records they need. Memories and embeddings stay on your machine.

It provides:

- a `memory` CLI for managing the library;
- an MCP server for any harness that supports local STDIO servers;
- an optional Pi extension with automatic recall and `/remember_this` to control
  the input data stored in memory.

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
```

Run `memory COMMAND --help` for all options. Mutating commands show a preview
and require confirmation.

The first command starts a shared background service automatically. Stop it with
`memory maintenance stop`; otherwise it ends when the laptop shuts down.

## MCP integration

The `pocket-recall-mcp` executable exposes three tools:

- `search(query)`: compact candidates;
- `fetch(id)`: one complete active record;
- `save(title, body, aliases)`: create one record.

Any MCP-compatible harness that supports local STDIO servers can launch this
executable. Configure read tools to run automatically and `save` to require
approval.

For Codex development setup:

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

## Pi integration

The optional [`pi-extension/`](pi-extension/) package adds workspace-gated
automatic recall and `/remember_this`. Its README contains the development setup
and configuration.

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
events contain no memory bodies and expire after 30 days.

## Project structure

```text
src/pocket_recall/
├── storage/      authoritative, search, audit, and snapshot persistence
├── retrieval/    indexing and result selection
├── embeddings/   local model configuration and lifecycle
├── transport/    shared service, client, and protocol
├── mcp/          harness-neutral MCP adapter
└── cli.py        human-facing command line

pi-extension/     optional Pi adapter
```

Development rules and architectural gotchas are in [`AGENTS.md`](AGENTS.md).

## Development checks

```sh
.venv/bin/python -m compileall -q src
.venv/bin/python -m isort --check-only src
.venv/bin/python -m black --check src
.venv/bin/python -m pip check
```
