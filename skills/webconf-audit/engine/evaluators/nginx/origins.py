from __future__ import annotations

from engine.analyzers.nginx import origins as az
from engine.model import Finding, Signal

_REMEDIATION = (
    "Tighten the Origin/Referer regex: anchor it, escape dots in domain labels, "
    "and reject suffix/prefix tricks (e.g. evil.com matching .*example.com)."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_WEAK:
            continue
        severity = (sig.data or {}).get("severity") or "medium"
        name = (sig.data or {}).get("name") or "referrer"
        examples = (sig.data or {}).get("invalid_examples") or []
        out.append(
            Finding(
                id="nginx.origins.weak_validation",
                severity=severity,
                title=f'Weak {name} validation regex',
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary=('matches: "' + '", "'.join(examples[:3]) + '"') if examples else None,
            )
        )
    return out
