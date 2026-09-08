#!/usr/bin/env python3
"""Validate nginx/apache corpus configs parse into a coherent AST."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.apache.parser import ApacheAdapter  # noqa: E402
from adapters.nginx.parser import NginxAdapter  # noqa: E402


def count_nodes(node) -> int:
    return 1 + sum(count_nodes(c) for c in node.children)


def ast_checks(doc, kind: str) -> list[str]:
    """Structural sanity checks beyond 'parsed without exception'."""
    issues: list[str] = []
    kinds = Counter()
    names = Counter()
    for n in doc.root.walk():
        kinds[n.kind] += 1
        if n.kind in {"directive", "block", "include"}:
            names[n.name] += 1
        if n.kind == "block" and n.name == "location" and kind == "nginx":
            # location should usually have a path arg (modifier optional)
            if not n.args:
                issues.append(f"location block with empty args at {n.file}:{n.line}")
        if n.kind == "directive" and not n.name:
            issues.append(f"directive with empty name at {n.file}:{n.line}")
        if n.kind == "map_entry" and n.name == "":
            issues.append(f"map_entry with empty name at {n.file}:{n.line}")
    meaningful = (
        kinds.get("directive", 0)
        + kinds.get("block", 0)
        + kinds.get("include", 0)
        + kinds.get("map_entry", 0)
    )
    if meaningful == 0:
        issues.append("AST has no directives/blocks/includes (empty or comment-only)")
    return issues


def validate_file(kind: str, path: Path) -> dict:
    adapter = NginxAdapter() if kind == "nginx" else ApacheAdapter()
    try:
        result = adapter.parse_file(path)
    except Exception as exc:  # noqa: BLE001 — corpus runner wants all failures
        return {"file": path.name, "ok": False, "error": str(exc)[:300]}
    nodes = count_nodes(result.document.root)
    issues = ast_checks(result.document, kind)
    return {
        "file": path.name,
        "ok": True,
        "nodes": nodes,
        "warnings": len(result.warnings),
        "warn_sample": result.warnings[:3],
        "ast_issues": issues,
    }


def main() -> int:
    corpus = ROOT / "fixtures" / "corpus"
    report: dict = {}
    exit_code = 0
    for kind in ("nginx", "apache"):
        d = corpus / kind
        ok, fail = [], []
        if not d.is_dir():
            report[kind] = {"ok": [], "fail": [{"file": str(d), "error": "missing dir"}]}
            exit_code = 1
            continue
        for path in sorted(d.glob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".conf", ".htaccess", ".in", ".tmpl", ".example", ".nginx"} and not path.name.endswith(
                (".conf.in", ".htaccess")
            ):
                # still try .conf-like names without suffix filters loosely
                if not any(path.name.endswith(s) for s in (".conf", ".htaccess", ".in", ".example")):
                    continue
            row = validate_file(kind, path)
            if row.get("ok") and not row.get("ast_issues"):
                ok.append(row)
            elif row.get("ok"):
                # parsed but AST issues — treat as soft-fail for now
                row["ok"] = False
                row["error"] = "ast_issues: " + "; ".join(row["ast_issues"][:3])
                fail.append(row)
                exit_code = 1
            else:
                fail.append(row)
                exit_code = 1
        report[kind] = {
            "ok": [{"file": r["file"], "nodes": r["nodes"], "warnings": r["warnings"], "warn_sample": r.get("warn_sample", [])} for r in ok],
            "fail": [{"file": r["file"], "error": r.get("error", "")} for r in fail],
            "summary": {"ok": len(ok), "fail": len(fail)},
        }
        print(f"{kind}: ok={len(ok)} fail={len(fail)}")
        for r in fail:
            print(f"  FAIL {r['file']}: {r.get('error', '')[:160]}")
    out = Path("/tmp/corpus_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
