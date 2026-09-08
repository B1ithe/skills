from __future__ import annotations

from engine.evaluators.nginx import (
    add_header_multiline,
    add_header_redefinition,
    alias_traversal,
    host_spoofing,
    http_splitting,
    origins,
    ssrf,
    valid_referers,
)
from engine.model import Finding, Signal

_EVALUATORS = (
    http_splitting,
    host_spoofing,
    ssrf,
    origins,
    add_header_redefinition,
    add_header_multiline,
    valid_referers,
    alias_traversal,
)


def run_all(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for mod in _EVALUATORS:
        out.extend(mod.evaluate(signals, hop_id=hop_id))
    return out
