#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'mumutool-skill: %s\n' "$*" >&2
  exit 1
}

if [[ -n "${MUMUTOOL_PATH:-}" ]]; then
  tool="$MUMUTOOL_PATH"
else
  app="${MUMUPLAYER_APP:-/Applications/MuMuPlayer.app}"
  tool="$app/Contents/MacOS/mumutool"
fi

if [[ ! -x "$tool" && -x "$HOME/Applications/MuMuPlayer.app/Contents/MacOS/mumutool" ]]; then
  tool="$HOME/Applications/MuMuPlayer.app/Contents/MacOS/mumutool"
fi

[[ -x "$tool" ]] || die "mumutool not found. Install MuMuPlayer for Mac or set MUMUTOOL_PATH."

exec "$tool" "$@"
