#!/usr/bin/env python3
"""Thin CLI entry — server logic lives in adapters/, not here.

Usage:
  python scripts/parse_config.py nginx /path/to/nginx.conf --pretty
  python scripts/parse_config.py apache /path/to/httpd.conf --pretty
  python scripts/parse_config.py nginx /path/to/nginx.conf \\
      --path-map /usr/local/nginx/conf=/path/to/local/conf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.base import get_adapter  # noqa: E402


def _parse_path_map(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"invalid --path-map {item!r}, expected SRC=DST")
        src, dst = item.split("=", 1)
        out[src] = dst
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse nginx/apache config into JSON AST")
    ap.add_argument("server", choices=["nginx", "apache", "httpd"])
    ap.add_argument("path", help="entry config file")
    ap.add_argument("--path-map", action="append", default=[], help="SRC=DST include rewrite")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    server = "apache" if args.server == "httpd" else args.server
    result = get_adapter(server).parse_file(args.path, path_map=_parse_path_map(args.path_map) or None)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2 if args.pretty else None))
    if result.warnings:
        print("\n# warnings:", file=sys.stderr)
        for w in result.warnings:
            print(f"# - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
