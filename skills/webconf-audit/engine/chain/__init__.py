from __future__ import annotations

"""Chain evaluators: combine HopResults into cross-hop Findings."""

from engine.chain import path_confusion
from engine.model import Finding, HopResult

_CHAIN = (path_confusion,)


def run_all(hops: list[HopResult]) -> list[Finding]:
    out: list[Finding] = []
    for mod in _CHAIN:
        out.extend(mod.evaluate(hops))
    return out
