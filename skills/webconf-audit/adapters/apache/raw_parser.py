from __future__ import annotations

"""Apache httpd.conf line-oriented tokenizer.

Apache omits trailing semicolons and uses <Section>...</Section> blocks.
"""

import re
from dataclasses import dataclass


@dataclass
class RawToken:
    kind: str  # comment | include | directive | section_open | section_close
    name: str
    args: list[str]
    line: int
    raw: str


_RE_COMMENT = re.compile(r"^\s*#(.*)$")
_RE_SECTION_OPEN = re.compile(r"^\s*<(\w+)(?:\s+(.*))?>\s*$")
_RE_SECTION_CLOSE = re.compile(r"^\s*</(\w+)>\s*$")
_RE_INCLUDE = re.compile(r"^\s*(IncludeOptional|Include)\s+(.+?)\s*$", re.I)
_RE_ARG = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"|(\S+)')


def split_args(s: str | None) -> list[str]:
    if not s or not s.strip():
        return []
    out: list[str] = []
    for m in _RE_ARG.finditer(s.strip()):
        out.append(m.group(1) if m.group(1) is not None else m.group(2))
    return out


def tokenize_apache(text: str) -> list[RawToken]:
    logical: list[tuple[int, str]] = []
    buf = ""
    start_line = 1
    for i, line in enumerate(text.splitlines(), start=1):
        if not buf:
            start_line = i
        if line.rstrip().endswith("\\") and not line.lstrip().startswith("#"):
            buf += line.rstrip()[:-1]
            continue
        buf += line
        logical.append((start_line, buf))
        buf = ""
    if buf:
        logical.append((start_line, buf))

    tokens: list[RawToken] = []
    for line_no, content in logical:
        stripped = content.strip()
        if not stripped:
            continue
        m = _RE_COMMENT.match(content)
        if m:
            tokens.append(RawToken("comment", "comment", [m.group(1).strip()], line_no, content))
            continue
        m = _RE_SECTION_CLOSE.match(content)
        if m:
            tokens.append(RawToken("section_close", m.group(1), [], line_no, content))
            continue
        m = _RE_SECTION_OPEN.match(content)
        if m:
            tokens.append(RawToken("section_open", m.group(1), split_args(m.group(2)), line_no, content))
            continue
        m = _RE_INCLUDE.match(content)
        if m:
            tokens.append(
                RawToken("include", m.group(1), [m.group(2).strip().strip('"')], line_no, content)
            )
            continue
        args = split_args(stripped)
        if not args:
            continue
        tokens.append(RawToken("directive", args[0], args[1:], line_no, content))
    return tokens
