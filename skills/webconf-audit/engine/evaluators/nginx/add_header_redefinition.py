from __future__ import annotations

from engine.analyzers.nginx import add_header_redefinition as az
from engine.model import Finding, Signal

_REMEDIATION = (
    "Nginx `add_header` in a nested context replaces ALL inherited add_header "
    "values. Re-declare every required security header in the child block, or "
    "set them only at the leaf level."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_DROPPED:
            continue
        dropped = (sig.data or {}).get("dropped") or []
        out.append(
            Finding(
                id="nginx.add_header_redefinition.dropped",
                severity="medium",
                title='Nested add_header drops parent headers',
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary='dropped: "' + '", "'.join(dropped) + '"' if dropped else None,
            )
        )
    return out
