"""gixy-parity: weak Origin/Referer validation regex in if conditions.

gixy uses a custom Regexp generator to synthesize counterexamples. We combine:
1. structural checks (unescaped dots in the host, missing anchors)
2. a small set of evil probes against Python's re
"""
from __future__ import annotations

import re

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.origins"
SIG_WEAK = "client.origin_or_referer.weak_validation"

_TRUSTED_RE = re.compile(
    r"^https?://(?:[^/.]*\.){0,10}(?P<domain>[^/.]*\.[^/]{2,7})(?::\d*)?(?:/|\?|$)"
)
_OPTIONS_RE = re.compile(r"Options:\s*(\{.*\})")


def _options_https_only(root: Node) -> bool:
    import json

    for node in root.walk():
        if node.kind != "comment" or not node.args:
            continue
        m = _OPTIONS_RE.search(node.args[0])
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if data.get("https_only"):
            return True
    return False


def analyze(root: Node, *, hop_id: str, https_only: bool = False, **_kwargs) -> list[Signal]:
    # gixy simply fixtures sometimes embed options in a leading comment:
    #   # Options: {"domains": ["yandex.ru"], "https_only": true}
    file_https_only = https_only or _options_https_only(root)
    signals: list[Signal] = []
    for node in root.walk():
        if node.kind != "block" or node.name != "if" or len(node.args) < 3:
            continue
        variable, operand, pattern = node.args[0], node.args[1], node.args[2]
        if variable not in {"$http_referer", "$http_origin"}:
            continue
        if operand not in {"~", "~*", "!~", "!~*"}:
            continue
        if (pattern.startswith('"') and pattern.endswith('"')) or (
            pattern.startswith("'") and pattern.endswith("'")
        ):
            pattern = pattern[1:-1]

        reasons = _weakness_reasons(
            pattern, case_sensitive=operand in {"~", "!~"}, https_only=file_https_only
        )
        if not reasons:
            continue
        name = "origin" if variable == "$http_origin" else "referrer"
        severity = "high" if variable == "$http_origin" else "medium"
        signals.append(
            Signal(
                id=SIG_WEAK,
                hop_id=hop_id,
                issuer=ISSUER,
                evidence=[Evidence(file=node.file, line=node.line, snippet=astutil.snippet(node))],
                data={
                    "variable": variable,
                    "operand": operand,
                    "pattern": pattern,
                    "reasons": reasons,
                    "invalid_examples": [r for r in reasons if r.startswith("http")],
                    "name": name,
                    "severity": severity,
                },
            )
        )
    return signals


def _weakness_reasons(pattern: str, *, case_sensitive: bool, https_only: bool) -> list[str]:
    reasons: list[str] = []
    # Structural: unescaped '.' in hostname allows matching unintended hosts.
    if _host_has_unescaped_dot(pattern):
        reasons.append("unescaped_dot_in_host")
    if not pattern.startswith("^"):
        reasons.append("missing_start_anchor")
    if _has_unanchored_alternation(pattern):
        reasons.append("unanchored_alternation")
    if _missing_end_boundary(pattern):
        reasons.append("missing_end_boundary")
    # https_only policy but pattern still allows http://
    if https_only and re.search(r"https\?", pattern):
        reasons.append("http_allowed_under_https_only")
    # Open prefix before a fixed label: [^/]+label  can match evil+label on attacker host
    if re.search(r"\[\^/\]\+\w+", pattern):
        reasons.append("open_prefix_before_label")

    # Probe-based (catches some suffix / open patterns)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        cre = re.compile(pattern, flags)
    except re.error:
        return reasons

    probes = [
        "http://evil.com/",
        "https://evil.com/",
        "http://yandex.ru.evil.com/",
        "https://yandex.ru.evil.com/",
        "https://example.com.evil.com/",
        "https://exampleacom/",
        "https://yandexXru/",
    ]
    if https_only:
        probes = [p for p in probes if p.startswith("https://")]

    for value in probes:
        if cre.search(value) or cre.match(value):
            valid = _TRUSTED_RE.match(value)
            if not valid or valid.group("domain") == "evil.com" or "X" in value or "acom" in value:
                reasons.append(value)
    return reasons


def _host_has_unescaped_dot(pattern: str) -> bool:
    """True if a hostname-like segment contains `.` that is not `\\.`."""
    p = pattern.replace("\\/", "/")
    masked = re.sub(r"\\.", "\x00", p)
    # Slice from each :// to the next path delimiter (not stopping inside []).
    for m in re.finditer(r"://", masked):
        i = m.end()
        host_chars: list[str] = []
        depth = 0
        while i < len(masked):
            ch = masked[i]
            if ch == "[":
                depth += 1
            elif ch == "]" and depth:
                depth -= 1
            elif depth == 0 and ch in "/?$":
                break
            host_chars.append(ch)
            i += 1
        if "." in "".join(host_chars):
            return True
    # No scheme: any remaining unescaped dot is suspicious for domain checks
    if "://" not in masked and "." in masked:
        return True
    return False


def _missing_end_boundary(pattern: str) -> bool:
    """Host at end without `$` / `/` allows suffix tricks (example.com.evil.com)."""
    p = pattern.replace("\\/", "/").rstrip()
    if p.endswith("$") or p.endswith("/$") or p.endswith("/"):
        return False
    # ends with a domain-ish token
    return bool(re.search(r"(?:\\.|[A-Za-z0-9-])$", p))


def _has_unanchored_alternation(pattern: str) -> bool:
    """Top-level `|` where some branch is not start-anchored (gixy webvisor case)."""
    depth = 0
    branches = [""]
    for i, ch in enumerate(pattern):
        if ch == "(" and (i == 0 or pattern[i - 1] != "\\"):
            depth += 1
        elif ch == ")" and (i == 0 or pattern[i - 1] != "\\") and depth:
            depth -= 1
        if ch == "|" and depth == 0:
            branches.append("")
            continue
        branches[-1] += ch
    if len(branches) <= 1:
        return False
    return any(not b.startswith("^") for b in branches)
