#!/bin/bash
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

REQUESTS="${1:-}"
ROOT="${2:-}"
JOBS="${3:-1}"

if [ "$REQUESTS" = "--one" ]; then
  ROOT="$2"
  request="$3"
  IFS=$'\t' read -r version rel py_rel <<< "$request"
else
  request=""
fi

if [ -z "$REQUESTS" ] || [ -z "$ROOT" ]; then
  echo "Usage: /validate.sh <requests.tsv> <candidate-root>" >&2
  exit 2
fi

python_bin() {
  case "$1" in
    1.*|2.*) echo "/opt/pyenv/versions/2.7.18/bin/python" ;;
    3.0|3.1|3.2|3.3|3.4|3.5|3.6|3.7|3.8) echo "/opt/pyenv/versions/3.8.20/bin/python" ;;
    3.9|3.10|3.11) echo "/opt/pyenv/versions/3.11.9/bin/python" ;;
    3.12|3.13) echo "/opt/pyenv/versions/3.12.8/bin/python" ;;
    3.14) echo "/opt/pyenv/versions/3.14.0/bin/python" ;;
    *) echo "" ;;
  esac
}

sanitize_detail() {
  tr '\n\t' '  ' | sed 's/[[:space:]][[:space:]]*/ /g' | cut -c1-240
}

check_syntax() {
  local interpreter="$1"
  local file="$2"
  "$interpreter" - "$file" <<'PY'
import sys

path = sys.argv[1]
with open(path, "rb") as handle:
    source = handle.read()
compile(source, path, "exec")
PY
}

validate_one() {
  local version="$1"
  local rel="$2"
  local py_rel="$3"
  local file interpreter output detail
  [ -z "${rel:-}" ] && return 0

  file="$ROOT/$py_rel"
  if [ ! -s "$file" ]; then
    printf 'PARTIAL\t%s\tsyntax=missing-output\n' "$rel"
    return 0
  fi

  interpreter="$(python_bin "$version")"
  if [ -z "$interpreter" ] || [ ! -x "$interpreter" ]; then
    printf 'PERFECT\t%s\tsyntax=unavailable:%s\n' "$rel" "$version"
    return 0
  fi

  if output="$(check_syntax "$interpreter" "$file" 2>&1)"; then
    printf 'PERFECT\t%s\tsyntax=ok\n' "$rel"
  else
    detail="$(printf '%s' "$output" | sanitize_detail)"
    printf 'PARTIAL\t%s\tsyntax=error:%s\n' "$rel" "$detail"
  fi
}

if [ -n "$request" ]; then
  validate_one "$version" "$rel" "$py_rel"
  exit 0
fi

while IFS= read -r request; do
  printf '%s\0' "$request"
done < "$REQUESTS" \
  | xargs -0 -r -n 1 -P "$JOBS" "$SELF" --one "$ROOT"
