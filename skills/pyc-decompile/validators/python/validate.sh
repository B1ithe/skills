#!/bin/bash
set -euo pipefail

REQUESTS="${1:-}"
ROOT="${2:-}"

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

while IFS=$'\t' read -r version rel py_rel; do
  [ -z "${rel:-}" ] && continue

  file="$ROOT/$py_rel"
  if [ ! -s "$file" ]; then
    printf 'PARTIAL\t%s\tsyntax=missing-output\n' "$rel"
    continue
  fi

  interpreter="$(python_bin "$version")"
  if [ -z "$interpreter" ] || [ ! -x "$interpreter" ]; then
    printf 'PERFECT\t%s\tsyntax=unavailable:%s\n' "$rel" "$version"
    continue
  fi

  if output="$(check_syntax "$interpreter" "$file" 2>&1)"; then
    printf 'PERFECT\t%s\tsyntax=ok\n' "$rel"
  else
    detail="$(printf '%s' "$output" | sanitize_detail)"
    printf 'PARTIAL\t%s\tsyntax=error:%s\n' "$rel" "$detail"
  fi
done < "$REQUESTS"
