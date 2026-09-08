from __future__ import annotations

"""Chain evaluators: combine HopResults into cross-hop Findings.

Phase 6 will add real nginx→apache rules. For now we provide a stub that
returns no findings but keeps the runner contract stable.
"""

from engine.model import Finding, HopResult


def run_all(hops: list[HopResult]) -> list[Finding]:
    # Placeholder: no chain rules yet.
    return []
