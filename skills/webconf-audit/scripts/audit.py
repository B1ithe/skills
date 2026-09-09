#!/usr/bin/env python3
"""Thin CLI: audit nginx/apache configs (and multi-hop pipeline).

Usage:
  python scripts/audit.py nginx fixtures/nginx/minimal.conf --pretty

  # Different kinds (kind-keyed maps still work):
  python scripts/audit.py pipeline \\
      --hop nginx:/a/nginx.conf \\
      --hop apache:/b/httpd.conf \\
      --hop-path-map nginx:/usr/local/nginx/conf=/local/a \\
      --hop-path-map apache:conf=/local/b --pretty

  # Two nginx hops (must key maps by hop id or index, not only kind):
  python scripts/audit.py pipeline \\
      --hop front=nginx:/front/nginx.conf \\
      --hop back=nginx:/back/nginx.conf \\
      --hop-path-map front:/usr/local/nginx/conf=/local/front/conf \\
      --hop-path-map back:/etc/nginx=/local/back/conf --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.runner import audit_apache_file, audit_nginx_file, audit_pipeline  # noqa: E402

_KNOWN_KINDS = frozenset({"nginx", "apache", "httpd"})


def _parse_path_map(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"invalid --path-map {item!r}, expected SRC=DST")
        src, dst = item.split("=", 1)
        out[src] = dst
    return out


def _parse_hop_path_maps(items: list[str] | None) -> dict[str, dict[str, str]]:
    """Parse --hop-path-map KEY:SRC=DST into {KEY: {SRC: DST}}.

    KEY may be:
      - hop id (e.g. front, back, nginx-0)
      - hop index as decimal string (e.g. 0, 1)
      - server kind (e.g. nginx, apache) — shared by all hops of that kind
    """
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for item in items or []:
        if ":" not in item or "=" not in item:
            raise SystemExit(
                f"invalid --hop-path-map {item!r}, expected KEY:SRC=DST "
                f"(KEY = hop id | index | kind)"
            )
        key, rest = item.split(":", 1)
        if "=" not in rest:
            raise SystemExit(f"invalid --hop-path-map {item!r}, expected KEY:SRC=DST")
        src, dst = rest.split("=", 1)
        out[key.strip()][src] = dst
    return dict(out)


def _parse_hop_spec(spec: str, index: int) -> tuple[str, str, str]:
    """Return (hop_id, kind, path).

    Forms:
      kind:path
      id=kind:path
    """
    rest = spec
    hop_id: str | None = None
    if "=" in spec:
        maybe_id, after = spec.split("=", 1)
        kind_part = after.split(":", 1)[0]
        if kind_part in _KNOWN_KINDS:
            hop_id = maybe_id.strip()
            rest = after
    if ":" not in rest:
        raise SystemExit(f"invalid --hop {spec!r}, expected kind:path or id=kind:path")
    kind, path = rest.split(":", 1)
    kind = kind.strip()
    if kind not in _KNOWN_KINDS:
        raise SystemExit(f"invalid --hop {spec!r}, unknown kind {kind!r}")
    if not hop_id:
        hop_id = f"{kind}-{index}"
    return hop_id, kind, path


def _path_map_for_hop(
    *,
    hop_id: str,
    kind: str,
    index: int,
    global_map: dict[str, str],
    hop_maps: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """Merge maps: global < kind < index < hop_id (later wins)."""
    path_map = dict(global_map)
    for key in (kind, str(index), hop_id):
        path_map.update(hop_maps.get(key) or {})
    return path_map or None


def _print_finding(prefix: str, f: dict) -> None:
    print(f"{prefix}[{f['severity']}] {f['id']}: {f['title']}", file=sys.stderr)
    for av in f.get("affected_versions") or []:
        comp = av.get("component", "?")
        vers = av.get("versions", "?")
        note = av.get("note") or ""
        print(f"{prefix}  versions: {comp} {vers}" + (f" — {note}" if note else ""), file=sys.stderr)


def _summarize_hop(result: dict) -> None:
    signals = result.get("signals") or []
    findings = result.get("findings") or []
    hop = result.get("hop") or {}
    print(
        f"\n# hop={hop.get('id')} kind={hop.get('kind')} "
        f"signals={len(signals)} findings={len(findings)}",
        file=sys.stderr,
    )
    for f in findings:
        _print_finding("# ", f)


def _summarize_pipeline(result: dict) -> None:
    print(f"\n# pipeline hops={len(result.get('hops') or [])}", file=sys.stderr)
    for hop in result.get("hops") or []:
        _summarize_hop(hop)
    chain = result.get("findings") or []
    print(
        f"# chain_findings={len(chain)} all_findings={len(result.get('all_findings') or [])}",
        file=sys.stderr,
    )
    for f in chain:
        _print_finding("# [chain]", f)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit web server config (signals + findings)")
    ap.add_argument("server", choices=["nginx", "apache", "httpd", "pipeline"])
    ap.add_argument("path", nargs="?", help="entry config (single-hop mode)")
    ap.add_argument(
        "--path-map",
        action="append",
        default=[],
        help="global SRC=DST include remap (lowest priority)",
    )
    ap.add_argument(
        "--hop-path-map",
        action="append",
        default=[],
        help=(
            "include remap keyed by hop id, hop index, or kind: KEY:SRC=DST "
            "(repeatable). For two nginx hops use id=... on --hop and key maps by id."
        ),
    )
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument(
        "--hop",
        action="append",
        default=[],
        help="pipeline hop: kind:path or id=kind:path (repeatable)",
    )
    args = ap.parse_args()
    global_map = _parse_path_map(args.path_map)
    hop_maps = _parse_hop_path_maps(args.hop_path_map)

    if args.server == "pipeline" or args.hop:
        hops = []
        for i, spec in enumerate(args.hop):
            hop_id, kind, path = _parse_hop_spec(spec, i)
            path_map = _path_map_for_hop(
                hop_id=hop_id,
                kind=kind,
                index=i,
                global_map=global_map,
                hop_maps=hop_maps,
            )
            hops.append(
                {
                    "kind": kind,
                    "path": path,
                    "hop_id": hop_id,
                    "path_map": path_map,
                }
            )
        if not hops and args.path:
            path_map = _path_map_for_hop(
                hop_id="nginx-0",
                kind="nginx",
                index=0,
                global_map=global_map,
                hop_maps=hop_maps,
            )
            hops.append(
                {"kind": "nginx", "path": args.path, "hop_id": "nginx-0", "path_map": path_map}
            )
        if not hops:
            raise SystemExit("pipeline mode requires --hop kind:path")
        result = audit_pipeline(hops).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        _summarize_pipeline(result)
        return

    if not args.path:
        raise SystemExit("path is required for single-hop mode")

    kind = "apache" if args.server == "httpd" else args.server
    path_map = _path_map_for_hop(
        hop_id=kind,
        kind=kind,
        index=0,
        global_map=global_map,
        hop_maps=hop_maps,
    )

    if args.server in ("apache", "httpd"):
        result = audit_apache_file(args.path, path_map=path_map).to_dict()
    else:
        result = audit_nginx_file(args.path, path_map=path_map).to_dict()

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    _summarize_hop(result)


if __name__ == "__main__":
    main()
