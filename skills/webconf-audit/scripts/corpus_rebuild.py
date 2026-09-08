#!/usr/bin/env python3
"""Rebuild fixtures/corpus from downloaded/cloned real-world configs."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from corpus_sanitize import looks_like_config, sanitize  # noqa: E402

SOURCES = [
    Path("/tmp/webconf-corpus/nginx"),
    Path("/tmp/webconf-corpus/apache"),
    Path("/tmp/webconf-corpus/raw2/nginx"),
    Path("/tmp/webconf-corpus/raw2/apache"),
    Path("/tmp/webconf-repos"),
]


def guess_kind(path: Path, text: str) -> str | None:
    posix = path.as_posix().lower()
    name = path.name.lower()
    if path.suffix == ".htaccess" or "/httpd/" in posix or name.startswith("httpd-") or "httpd-" in name:
        return "apache"
    if "proxy-html" in name or name.endswith(".conf.in"):
        # httpd .in templates
        if looks_like_config(text, "apache"):
            return "apache"
    if re.search(r"(?i)<(?:virtualhost|ifmodule|directory|location)\b", text[:4000]):
        if not re.search(r"(?m)^\s*(?:server|http|events)\s*\{", text[:4000]):
            return "apache"
    # Prefer apache when both match (e.g. comments mentioning nginx + Apache Listen).
    apache_ok = looks_like_config(text, "apache")
    nginx_ok = looks_like_config(text, "nginx")
    if apache_ok and not nginx_ok:
        return "apache"
    if nginx_ok and not apache_ok:
        return "nginx"
    if apache_ok and nginx_ok:
        if any(x in posix for x in ("/apache", "/httpd")) or "httpd" in name or name.endswith(".conf.in"):
            return "apache"
        return "nginx"
    return None


def iter_candidates():
    skip_names = {
        "doxygen.conf",
        "reflex.conf",
        "oauth2-proxy.cfg.example",
        "oauth2-proxy.service.example",
        "prometheus_all.conf",
        "prometheus_template",
    }
    for root in SOURCES:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            name = p.name.lower()
            if name in skip_names:
                continue
            if name.endswith(
                (".conf", ".conf.in", ".htaccess", ".nginx", ".example", ".conf.tmpl", ".conf.template")
            ) or name == "nginx.conf.sample":
                yield p


def main() -> int:
    out = {
        "nginx": ROOT / "fixtures" / "corpus" / "nginx",
        "apache": ROOT / "fixtures" / "corpus" / "apache",
    }
    for d in out.values():
        if d.exists():
            for child in d.iterdir():
                child.unlink()
        else:
            d.mkdir(parents=True)

    seen: set[str] = set()
    kept = {"nginx": 0, "apache": 0}
    idx = {"nginx": 0, "apache": 0}
    skipped: list[tuple[str, str]] = []

    for src in sorted(iter_candidates(), key=lambda p: str(p)):
        text = src.read_text(encoding="utf-8", errors="replace")
        kind = guess_kind(src, text)
        if kind is None or not looks_like_config(text, kind):
            skipped.append((src.name, "not-config"))
            continue
        cleaned = sanitize(text, kind=kind)
        if cleaned.count("{{") > 5 or cleaned.count("{%") > 5:
            skipped.append((src.name, "still-templated"))
            continue
        digest = hashlib.sha1(cleaned.encode()).hexdigest()
        if digest in seen:
            skipped.append((src.name, "dup"))
            continue
        seen.add(digest)
        idx[kind] += 1
        dest = out[kind] / f"{idx[kind]:03d}-{src.stem.replace(' ', '_')}{src.suffix or '.conf'}"
        dest.write_text(cleaned, encoding="utf-8")
        kept[kind] += 1

    print("kept", kept, "skipped", len(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
