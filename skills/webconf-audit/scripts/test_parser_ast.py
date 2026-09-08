#!/usr/bin/env python3
"""Focused AST regressions for nginx/apache parsers + corpus smoke."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.apache.parser import ApacheAdapter
from adapters.nginx.parser import NginxAdapter


def _names(doc):
    return [(n.kind, n.name) for n in doc.root.walk()]


def test_upstream_is_not_hash():
    r = NginxAdapter().parse_text("upstream b { server 1.2.3.4:80; keepalive 8; }")
    up = next(n for n in r.document.root.walk() if n.kind == "block" and n.name == "upstream")
    assert [c.kind for c in up.children] == ["directive", "directive"]
    assert [c.name for c in up.children] == ["server", "keepalive"]


def test_types_allows_comments():
    r = NginxAdapter().parse_text("types {\n # note about wasm\n application/wasm wasm;\n}")
    kinds = {n.kind for n in r.document.root.walk()}
    assert "comment" in kinds and "map_entry" in kinds
    entry = next(n for n in r.document.root.walk() if n.kind == "map_entry")
    assert entry.name == "application/wasm" and entry.args == ["wasm"]


def test_map_empty_quoted_key():
    r = NginxAdapter().parse_text("map $a $b { default upgrade; '' close; }")
    keys = {n.name: n.args for n in r.document.root.walk() if n.kind == "map_entry"}
    assert keys["default"] == ["upgrade"]
    assert keys['""'] == ["close"]


def test_location_modifiers():
    r = NginxAdapter().parse_text(
        "server { location = /exact { return 200; } location ~* \\.php$ { return 200; } }"
    )
    locs = [n for n in r.document.root.walk() if n.kind == "block" and n.name == "location"]
    assert locs[0].args[:1] == ["="]
    assert locs[1].args[:1] == ["~*"]


def test_apache_htaccess_shape():
    text = """
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule ^ index.php [L]
</IfModule>
"""
    r = ApacheAdapter().parse_text(text)
    names = _names(r.document)
    assert ("block", "IfModule") in names
    assert ("directive", "RewriteEngine") in names
    assert ("directive", "RewriteRule") in names


def test_corpus_all_parse():
    corpus = ROOT / "fixtures" / "corpus"
    for kind, adapter in (("nginx", NginxAdapter()), ("apache", ApacheAdapter())):
        d = corpus / kind
        assert d.is_dir(), d
        files = sorted(p for p in d.iterdir() if p.is_file() and p.name != "MANIFEST.json")
        assert files, f"empty corpus {kind}"
        for path in files:
            result = adapter.parse_file(path)
            meaningful = [
                n
                for n in result.document.root.walk()
                if n.kind in {"directive", "block", "include", "map_entry"}
            ]
            assert meaningful, f"{path} produced empty AST"


def main() -> int:
    tests = [
        test_upstream_is_not_hash,
        test_types_allows_comments,
        test_map_empty_quoted_key,
        test_location_modifiers,
        test_apache_htaccess_shape,
        test_corpus_all_parse,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"{failed} failed")
        return 1
    print("ALL PARSER AST TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
