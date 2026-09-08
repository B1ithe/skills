from __future__ import annotations

from engine.analyzers.nginx import add_header_multiline as az
from engine.model import Finding, Signal

_REMEDIATION = (
    "Avoid folded/multiline header values (RFC 7230). Put the header on one "
    "line, or split into multiple add_header directives."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_MULTILINE:
            continue
        out.append(
            Finding(
                id="nginx.add_header_multiline.value",
                severity="low",
                title="Found a multi-line header value",
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
            )
        )
    return out
