#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -P -- "$SCRIPT_DIR/.." && pwd)"
SCRIPT="$SCRIPT_DIR/ssh_skill.py"

if command -v uv >/dev/null 2>&1; then
  if [[ -z "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}"
    export UV_PROJECT_ENVIRONMENT="${SSH_SKILL_UV_ENVIRONMENT:-$CACHE_ROOT/ssh-skill/venv}"
  fi
  exec uv run --project "$SKILL_DIR" --locked python "$SCRIPT" "$@"
fi

for candidate in python3 python; do
  if ! command -v "$candidate" >/dev/null 2>&1; then
    continue
  fi
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    exec "$candidate" "$SCRIPT" "$@"
  fi
done

echo "Error: ssh-skill requires uv or Python 3.11+ with Paramiko already installed." >&2
echo "No compatible runtime was found; the skill does not install dependencies at runtime." >&2
exit 127
