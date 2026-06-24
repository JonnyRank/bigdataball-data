#!/bin/bash
# SessionStart hook: install Python dependencies so pytest and the pipeline
# scripts can run in a fresh Claude Code on the web session.
#
# Installs into a repo-local virtualenv (.venv) to avoid touching the system
# Python, then points the session's PATH at it. Idempotent: the venv is reused
# across runs and pip skips already-satisfied packages.
set -euo pipefail

# Only run in remote (Claude Code on the web) sessions. Locally you manage your
# own environment, so skip entirely and leave the developer's machine untouched.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python -m venv "$VENV_DIR"
fi

# Upgrading pip is a nice-to-have, not a requirement — never fail the session on it.
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip || true
"$VENV_DIR/bin/python" -m pip install --quiet -r requirements.txt -r requirements-dev.txt

# Make the venv the default interpreter for the rest of the session so `python`
# and `pytest` resolve to it in subsequent Bash commands.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export VIRTUAL_ENV=\"$VENV_DIR\"" >> "$CLAUDE_ENV_FILE"
  echo "export PATH=\"$VENV_DIR/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

exit 0
