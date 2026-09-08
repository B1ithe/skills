from __future__ import annotations

from engine.analyzers.nginx import valid_referers as az
from engine.model import Finding, Signal

_REMEDIATION = (
    'Do not use `none` in valid_referers — empty Referer is untrusted. Prefer '
    "`server_names` and explicit allowed hosts only."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_NONE:
            continue
        out.append(
            Finding(
                id="nginx.valid_referers.none",
                severity="high",
                title='valid_referers includes "none"',
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
            )
        )
    return out
