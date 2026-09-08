#!/usr/bin/env python3
"""Sanitize templated nginx/apache configs into parseable stand-ins for corpus tests.

Replaces Go/Jinja/ERB template markup with safe nginx/apache tokens so the AST
parser can exercise real project configs without requiring a render step.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Pure control / declaration lines — drop entirely.
_RE_GO_COMMENT = re.compile(r"\{\{-?\s*/\*.*?\*/\s*-?\}\}", re.DOTALL)
_RE_GO_LINE = re.compile(
    r"^\s*\{\{-?\s*(?:if|else|end|range|with|define|template|block|\$\w+)\b.*\}\}\s*$"
)
_RE_JINJA_LINE = re.compile(r"^\s*\{%-?\s*.*?-?%\}\s*$")
_RE_ERB_CTRL_LINE = re.compile(r"^\s*<%[^=][^%]*%>\s*$")
_RE_ERB_INLINE_CTRL = re.compile(r"<%[^=][^%]*%>")
_RE_ERB_EXPR = re.compile(r"<%=?\s*.*?%>")
_RE_JINJA_EXPR = re.compile(r"\{\%-?\s*.*?-?\%\}")
_RE_GO_EXPR = re.compile(r"\{\{-?.*?-?\}\}")
_RE_AT_AT = re.compile(r"@@[A-Za-z0-9_.-]+@@")
_RE_APACHE_AT = re.compile(r"@(?:rel_|exp_|std)?[A-Za-z0-9_]+@")

# After stripping, collapse empty values left behind by removals.
_RE_EMPTY_VALUE = re.compile(r"(?<=\s);\s*$")  # bare trailing " ;" after keyword — keep as-is
_RE_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def looks_like_config(text: str, kind: str) -> bool:
    """Heuristic: reject markdown/yaml/docker/php masquerading as .conf."""
    if not text or not text.strip():
        return False
    head = text.lstrip()[:800]
    lower_head = head.lower()
    body = text[:20000]
    body_l = body.lower()

    # Hard rejects for non-config formats (scan past leading comments).
    if re.search(r"(?m)^(FROM |#!|kind:|apiVersion:|services:|base_image:|<\?php|<img |<!DOCTYPE|<html)", text[:2000]):
        return False
    if re.search(r"(?m)^\[(global|www|PHP)\]", text[:1000]):
        return False  # php-fpm pool ini
    if "kong configuration file" in lower_head or re.search(r"(?m)^prefix\s*=", text[:2000]):
        # Kong's own declarative config (not nginx)
        if "server {" not in body and "http {" not in body:
            return False
    if head.startswith("---") and any(x in head for x in ("\nversion:", "\nslug:", "\nhassio_api:")):
        return False
    # Markdown / RST docs (even if they embed snippets later).
    if re.search(r"(?m)^#{1,3}\s+\S+", head) and "server {" not in text[:1500]:
        if any(x in lower_head for x in ("using a reverse", "installation", "readme", "official docker")):
            return False
    if "====" in text[:800] and "server {" not in text[:2500]:
        return False
    # Heavily Go-templated nginx-proxy style: mostly template, little static nginx.
    if len(re.findall(r"\{\{", text[:20000])) > 80:
        return False

    # Angie prometheus helper configs are not plain nginx.
    if re.search(r"(?m)^\s*prometheus_template\b", text[:4000]):
        return False

    if kind == "nginx":
        # Line-anchored markers so Apache <Location> / Listen do not false-positive.
        patterns = (
            r"(?m)^\s*server\s*\{",
            r"(?m)^\s*http\s*\{",
            r"(?m)^\s*events\s*\{",
            r"(?m)^\s*upstream\s+\S+",
            r"(?m)^\s*location\s+",
            r"(?m)^\s*worker_processes\b",
            r"(?m)^\s*listen\s+\S+",
            r"(?m)^\s*server_name\s+\S+",
            r"(?m)^\s*proxy_pass\s+\S+",
            r"(?m)^\s*map\s+\$",
            r"(?m)^\s*types\s*\{",
            r"(?m)^\s*fastcgi_param\s+",
            r"(?m)^\s*uwsgi_param\s+",
            r"(?m)^\s*scgi_param\s+",
            r"(?m)^\s*gzip\s+on\b",
            r"(?m)^\s*root\s+\S+;",
        )
        # Case-sensitive: nginx directives are lowercase; Apache uses Listen/ServerName.
        return any(re.search(p, text) for p in patterns)
    patterns = (
        r"(?i)<virtualhost\b",
        r"(?i)<directory\b",
        r"(?i)<ifmodule\b",
        r"(?i)<filesmatch\b",
        r"(?i)<files\b",
        r"(?i)<location\b",
        r"(?m)^\s*ServerRoot\b",
        r"(?m)^\s*DocumentRoot\b",
        r"(?m)^\s*LoadModule\b",
        r"(?m)^\s*RewriteRule\b",
        r"(?m)^\s*RewriteEngine\b",
        r"(?m)^\s*ProxyPass\b",
        r"(?m)^\s*ServerName\b",
        r"(?m)^\s*AllowOverride\b",
        r"(?m)^\s*Require\s+all\b",
        r"(?m)^\s*Header\s+(always|set)\b",
    )
    return any(re.search(p, text) for p in patterns)


def sanitize(text: str, *, kind: str = "nginx") -> str:
    # Strip block comments in go templates first.
    text = _RE_GO_COMMENT.sub("", text)

    out_lines: list[str] = []
    for line in text.splitlines():
        if _RE_GO_LINE.match(line) or _RE_JINJA_LINE.match(line) or _RE_ERB_CTRL_LINE.match(line):
            continue
        # Inline control tags that wrap a statement: keep the statement.
        line = _RE_ERB_INLINE_CTRL.sub("", line)
        line = _RE_JINJA_EXPR.sub("", line)
        # Expression placeholders → safe token without braces/angles.
        line = _RE_ERB_EXPR.sub("tmpl", line)
        line = _RE_GO_EXPR.sub("tmpl", line)
        line = _RE_AT_AT.sub("tmpl", line)
        if kind == "apache":
            line = _RE_APACHE_AT.sub("tmpl", line)
        line = _RE_MULTI_SPACE.sub(" ", line)
        # Drop lines that became empty or only whitespace/punctuation noise.
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        # Bare "tmpl" left as a statement (was a whole-line template) — drop.
        if stripped in {"tmpl", "tmpl;", "{", "}"}:
            # Keep braces; drop bare tmpl statements.
            if stripped in {"{", "}"}:
                out_lines.append(line)
            continue
        # Fix "location tmpl {" / "server_name tmpl;" style — already fine.
        # Fix empty directive values: "server_name ;" → "server_name tmpl;"
        if kind == "nginx":
            line = re.sub(
                r"\b(server_name|root|proxy_pass|fastcgi_pass|uwsgi_pass|listen|ssl_certificate"
                r"|ssl_certificate_key|alias|return|rewrite|set|add_header|include"
                r"|auth_basic_user_file|resolver|access_log|error_log)\s+;",
                r"\1 tmpl;",
                line,
            )
            # "location {" or "location ~ {" / "location ^~ {" with missing path
            line = re.sub(
                r"\blocation(\s+(?:~\*|~|\^~))?\s*\{",
                lambda m: f"location{m.group(1) or ''} / {{",
                line,
            )
        out_lines.append(line.rstrip())

    # Clean leftover empty runs at start from dropped template headers.
    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    return cleaned


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(f"usage: {argv[0]} <nginx|apache> <src> [dst]", file=sys.stderr)
        return 2
    kind, src = argv[1], Path(argv[2])
    dst = Path(argv[3]) if len(argv) > 3 else None
    text = src.read_text(encoding="utf-8", errors="replace")
    if not looks_like_config(text, kind):
        print(f"SKIP not-a-config: {src}", file=sys.stderr)
        return 1
    out = sanitize(text, kind=kind)
    if dst:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
