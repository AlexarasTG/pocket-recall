# Pocket Recall for Pi

Thin Pi representation layer for Pocket Recall. It adds conservative automatic
recall in configured workspaces and an explicitly approved `/remember_this` flow.
It never injects stored memory content at session startup.

## Development setup

Install and initialize Pocket Recall first. The `memory` executable must be on
`PATH`:

```sh
memory maintenance init
```

Create the optional Pi configuration:

```sh
mkdir -p ~/.config/pocket-recall
cp pi.example.json ~/.config/pocket-recall/pi.json
```

Missing or empty `enabledWorkspaceRoots` disables automatic recall. Paths are
resolved before containment checks. `/remember_this` remains available for
manual memory creation outside enabled workspaces.

Load the package directly while developing:

```sh
pi -e ./pi-extension
```

The extension talks directly to the fixed Pocket Recall Unix socket under
`~/.local/share/pocket-recall/`. If the socket is unavailable, it temporarily
uses `memory maintenance status` to start the service and ignores successful
command output.

## Behavior

Inside enabled workspaces, Pi receives a short fixed instruction and can call:

- `pocket_recall_search` for compact candidates;
- `pocket_recall_fetch` for one selected complete memory.

Each tool is limited to three calls per user turn. Memory content enters model
context only through tool results.

`/remember_this STATEMENT` temporarily exposes `pocket_recall_save`. The model
structures only that statement, then the extension opens a JSON editor. Submitting
the valid draft approves and saves it; cancelling saves nothing. Completing or
cancelling the request, or letting the agent settle, removes the one-use intent
and hides the save tool. The backend performs authoritative validation before
persistence.
