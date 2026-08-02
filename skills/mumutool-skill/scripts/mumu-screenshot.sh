#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'mumutool-skill: %s\n' "$*" >&2
  exit 1
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  die "usage: mumu-screenshot.sh <instance-index> [output.png]"
fi

index="$1"
timestamp="$(date '+%Y%m%d-%H%M%S')"
output="${2:-./tmp/mumutool-skill/mumu-${index}-${timestamp}.png}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$(dirname "$output")"
"$script_dir/mumu-adb.sh" "$index" exec-out screencap -p >"$output"
[[ -s "$output" ]] || die "screenshot was empty"

absolute_dir="$(cd "$(dirname "$output")" && pwd)"
printf '%s/%s\n' "$absolute_dir" "$(basename "$output")"
