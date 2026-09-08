from __future__ import annotations

from engine.evaluators.nginx import host_spoofing, http_splitting
from engine.model import Finding, Signal


def run_all(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    out.extend(http_splitting.evaluate(signals, hop_id=hop_id))
    out.extend(host_spoofing.evaluate(signals, hop_id=hop_id))
    return out
