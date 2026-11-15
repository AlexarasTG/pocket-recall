#!/bin/sh
# Install, format, verify, and restart Pocket Recall so the shared service runs the current code.
set -eu
cd "$(dirname "$0")/.."

python=.venv/bin/python
"$python" -m pip install --quiet --disable-pip-version-check --editable ".[dev]"
"$python" -m compileall -q src
"$python" -m isort --quiet src tests
"$python" -m black --quiet src tests
"$python" -m pytest -q
"$python" -m pip check
.venv/bin/memory maintenance stop
