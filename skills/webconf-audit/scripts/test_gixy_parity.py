#!/usr/bin/env python3
"""Regression: match yandex/gixy simply plugin fixtures (expect hit unless *_fp.conf)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.nginx.parser import NginxAdapter
from engine.analyzers import nginx as naz
from engine.evaluators import nginx as nev

PLUGIN_PREFIX = {
    "ssrf": "nginx.ssrf.",
    "host_spoofing": "nginx.host_spoofing.",
    "alias_traversal": "nginx.alias_traversal.",
    "add_header_redefinition": "nginx.add_header_redefinition.",
    "add_header_multiline": "nginx.add_header_multiline.",
    "valid_referers": "nginx.valid_referers.",
    "http_splitting": "nginx.http_splitting.",
    "origins": "nginx.origins.",
}


def audit_text(text: str):
    wrapped = text if ("server {" in text or "http {" in text) else "server {\n" + text + "\n}\n"
    root = NginxAdapter().parse_text(wrapped).document.root
    return nev.run_all(naz.run_all(root, hop_id="t"), hop_id="t")


def main() -> int:
    base = ROOT / "fixtures" / "gixy-simply"
    if not base.is_dir():
        print("FAIL missing fixtures/gixy-simply", file=sys.stderr)
        return 1
    failed = 0
    total = 0
    for plugin, prefix in PLUGIN_PREFIX.items():
        for conf in sorted((base / plugin).glob("*.conf")):
            total += 1
            expect = not conf.name.endswith("_fp.conf")
            try:
                finds = audit_text(conf.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {plugin}/{conf.name} PARSE {exc}")
                failed += 1
                continue
            got = any(f.id.startswith(prefix) for f in finds)
            if got != expect:
                print(f"FAIL {plugin}/{conf.name} expect_hit={expect} got={got}")
                failed += 1
            else:
                print(f"OK   {plugin}/{conf.name}")
    if failed:
        print(f"{failed}/{total} failed")
        return 1
    print(f"ALL {total} GIXY SIMPLY FIXTURES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
