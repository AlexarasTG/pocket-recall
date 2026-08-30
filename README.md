# Memory Manager

A general-purpose, local-first memory tool: explicit user-controlled writes,
compact search results, and selective full-record recall. No dependency on an
agent harness.

## Components

- `models.py`: editable drafts, authoritative records, and compact candidates.
- `config.py`: storage paths and limits; no implicit filesystem writes.
- `service.py`: mutation, listing, recovery, search, and fetch contracts.

Data-directory and workspace paths are explicit configuration. No developer
home directory or company workspace is built into the package. Empty workspace
allowlists disable automatic client activation.
