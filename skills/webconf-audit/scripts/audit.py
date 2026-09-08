#!/usr/bin/env python3
"""Thin CLI: audit nginx/apache configs (and multi-hop pipeline).

Usage:
  python scripts/audit.py nginx fixtures/nginx/minimal.conf --pretty
  python scripts/audit.py apache fixtures/apache/minimal.conf --pretty
  python scripts/audit.py pipeline \\
      --hop nginx:fixtures/nginx/minimal.conf \\
      --hop apache:fixtures/apache/minimal.conf --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.runner import audit_apache_file, audit_nginx_file, audit_pipeline  # noqa: E402


def _parse_path_map(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"invalid --path-map {item!r}, expected SRC=DST")
        src, dst = item.split("=", 1)
        out[src] = dst
    return out


def _summarize_hop(result: dict) -> None:
    signals = result.get("signals") or []
    findings = result.get("findings") or []
    print(f"\n# hop={result.get('hop', {}).get('kind')} signals={len(signals)} findings={len(findings)}", file=sys.stderr)
    for f in findings:
        print(f"# [{f['severity']}] {f['id']}: {f['title']}", file=sys.stderr)


def _summarize_pipeline(result: dict) -> None:
    print(f"\n# pipeline hops={len(result.get('hops') or [])}", file=sys.stderr)
    for hop in result.get("hops") or []:
        _summarize_hop(hop)
    chain = result.get("findings") or []
    print(f"# chain_findings={len(chain)} all_findings={len(result.get('all_findings') or [])}", file=sys.stderr)
    for f in chain:
        print(f"# [chain][{f['severity']}] {f['id']}: {f['title']}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit web server config (signals + findings)")
    ap.add_argument("server", choices=["nginx", "apache", "httpd", "pipeline"])
    ap.add_argument("path", nargs="?", help="entry config (single-hop mode)")
    ap.add_argument("--path-map", action="append", default=[])
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument(
        "--hop",
        action="append",
        default=[],
        help="pipeline mode: kind:path (repeatable), e.g. nginx:/a/nginx.conf",
    )
    args = ap.parse_args()
    path_map = _parse_path_map(args.path_map) or None

    if args.server == "pipeline" or args.hop:
        hops = []
        for spec in args.hop:
            if ":" not in spec:
                raise SystemExit(f"invalid --hop {spec!r}, expected kind:path")
            kind, path = spec.split(":", 1)
            hops.append({"kind": kind, "path": path, "path_map": path_map})
        if not hops and args.path:
            hops.append({"kind": "nginx", "path": args.path, "path_map": path_map})
        if not hops:
            raise SystemExit("pipeline mode requires --hop kind:path")
        result = audit_pipeline(hops).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        _summarize_pipeline(result)
        return

    if not args.path:
        raise SystemExit("path is required for single-hop mode")

    if args.server in ("apache", "httpd"):
        result = audit_apache_file(args.path, path_map=path_map).to_dict()
    else:
        result = audit_nginx_file(args.path, path_map=path_map).to_dict()

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    _summarize_hop(result)


if __name__ == "__main__":
    main()
