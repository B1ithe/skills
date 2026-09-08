from __future__ import annotations

from engine.analyzers.nginx import alias_traversal as az
from engine.model import Finding, Signal

_REMEDIATION = (
    "Terminate prefix locations with `/` when using `alias` that points at a "
    "directory (e.g. `location /files/ { alias /home/; }`), or use a root-based "
    "layout instead of alias."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_ALIAS:
            continue
        severity = (sig.data or {}).get("severity") or "high"
        out.append(
            Finding(
                id="nginx.alias_traversal.prefix",
                severity=severity,
                title="Path traversal via misconfigured alias",
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary=(
                    f"location {(sig.data or {}).get('location')} + "
                    f"alias {(sig.data or {}).get('alias')}"
                ),
            )
        )
    return out
