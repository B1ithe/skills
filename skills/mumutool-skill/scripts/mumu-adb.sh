#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'mumutool-skill: %s\n' "$*" >&2
  exit 1
}

if [[ $# -lt 2 ]]; then
  die "usage: mumu-adb.sh <instance-index> <adb-arguments...>"
fi

index="$1"
shift
[[ "$index" =~ ^[0-9]+$ ]] || die "instance index must be one non-negative integer"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info="$("$script_dir/mumutool.sh" info "$index")"

port="$(
  python3 -c '
import json, sys
data = json.load(sys.stdin)
if data.get("errcode") != 0:
    raise SystemExit(data.get("message") or "mumutool info failed")
item = data.get("return", {})
if "results" in item:
    matches = [x for x in item["results"] if str(x.get("index")) == sys.argv[1]]
    if not matches:
        raise SystemExit("instance not found")
    item = matches[0]
if item.get("state") != "running":
    raise SystemExit("instance is not running: " + str(item.get("state", "unknown")))
port = item.get("adb_port")
if not port:
    raise SystemExit("running instance did not report adb_port")
print(port)
' "$index" <<<"$info"
)"

adb_bin="${ADB:-}"
if [[ -z "$adb_bin" ]]; then
  adb_bin="$(command -v adb || true)"
fi
[[ -n "$adb_bin" && -x "$adb_bin" ]] || die "adb not found. Install Android platform tools or set ADB."

serial="127.0.0.1:$port"
"$adb_bin" connect "$serial" >/dev/null
exec "$adb_bin" -s "$serial" "$@"
