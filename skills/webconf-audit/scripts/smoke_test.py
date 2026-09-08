#!/usr/bin/env python3
"""End-to-end smoke test for parse + audit + pipeline. Exit 0 on success."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.base import get_adapter
from adapters.nginx.variables import NginxVarModel
from engine.runner import audit_apache_file, audit_nginx_file, audit_pipeline


def _ok(msg: str) -> None:
    print(f"OK  {msg}")


def _fail(msg: str) -> None:
    print(f"FAIL {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    # variables
    m = NginxVarModel()
    if not m.may_contain_newline("uri") or m.may_contain_newline("request_uri"):
        _fail("variables can_contain basics")
    _ok("variables")

    # parse fixtures
    ngx = get_adapter("nginx").parse_file(ROOT / "fixtures/nginx/minimal.conf")
    if not any(n.name == "http" for n in ngx.document.root.children if n.kind == "block"):
        _fail("nginx parse fixture")
    _ok("parse nginx fixture")

    apa = get_adapter("apache").parse_file(ROOT / "fixtures/apache/minimal.conf")
    if not any(n.name == "VirtualHost" for n in apa.document.root.children if n.kind == "block"):
        _fail("apache parse fixture")
    _ok("parse apache fixture")

    # audit vulnerable
    vuln = audit_nginx_file(ROOT / "fixtures/nginx/minimal.conf")
    if not any(f.id.startswith("nginx.http_splitting") for f in vuln.findings):
        _fail(f"expected splitting finding, got {vuln.findings}")
    _ok("audit vulnerable nginx")

    # audit safe
    safe = audit_nginx_file(ROOT / "fixtures/nginx/safe_request_uri.conf")
    if safe.findings or safe.signals:
        _fail(f"safe_request_uri should be clean: {safe.to_dict()}")
    _ok("audit safe_request_uri")

    # apache hop (no analyzers yet)
    ah = audit_apache_file(ROOT / "fixtures/apache/minimal.conf")
    if ah.hop.kind != "apache" or "behaviors" not in ah.to_dict():
        _fail("apache hop result shape")
    _ok("audit apache hop shape")

    # pipeline
    pipe = audit_pipeline(
        [
            {"kind": "nginx", "path": str(ROOT / "fixtures/nginx/minimal.conf")},
            {"kind": "apache", "path": str(ROOT / "fixtures/apache/minimal.conf")},
        ]
    )
    d = pipe.to_dict()
    if len(d["hops"]) != 2:
        _fail("pipeline hop count")
    if d["hops"][0]["findings"] == []:
        _fail("pipeline should keep nginx hop findings")
    # chain stub: top-level findings empty for now
    if d["findings"] != []:
        _fail(f"chain stub should be empty, got {d['findings']}")
    if len(d["all_findings"]) < 1:
        _fail("all_findings should include hop findings")
    _ok("pipeline shape")

    # optional external samples (set WEBCONF_SMOKE_NGINX / WEBCONF_SMOKE_NGINX_MAPPED)
    crlf = Path(os.environ["WEBCONF_SMOKE_NGINX"]) if os.environ.get("WEBCONF_SMOKE_NGINX") else None
    if crlf and crlf.is_file():
        r = audit_nginx_file(crlf)
        if not r.findings:
            _fail("WEBCONF_SMOKE_NGINX should yield findings")
        _ok(f"external nginx findings={len(r.findings)}")

    usm = Path(os.environ["WEBCONF_SMOKE_NGINX_MAPPED"]) if os.environ.get("WEBCONF_SMOKE_NGINX_MAPPED") else None
    if usm and usm.is_file():
        mapped_root = os.environ.get("WEBCONF_SMOKE_PATH_MAP_ROOT", "/usr/local/nginx/conf")
        r = audit_nginx_file(usm, path_map={mapped_root: str(usm.parent)})
        ids = [f.id for f in r.findings]
        if "nginx.host_trust.forwarded_host" not in ids:
            _fail(f"mapped sample expected host_trust, got {ids}")
        _ok("mapped nginx host_trust")

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
