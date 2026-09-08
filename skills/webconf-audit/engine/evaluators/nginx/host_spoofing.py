from __future__ import annotations

from engine.analyzers.nginx import host_trust as ht
from engine.model import Finding, Signal

_REMEDIATION = (
    "Do not forward client-controlled Host / X-Forwarded-Host to upstream as "
    "authoritative identity without an allowlist. Prefer a fixed Host or "
    "validate against known server names."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    findings: list[Finding] = []
    for sig in signals:
        if sig.id == ht.SIG_FORWARDED_HOST:
            findings.append(
                Finding(
                    id="nginx.host_trust.forwarded_host",
                    severity="medium",
                    title="Client X-Forwarded-Host may be trusted upstream",
                    category="single_hop",
                    hop_ids=[hop_id],
                    based_on=[sig.id],
                    evidence=list(sig.evidence),
                    remediation=_REMEDIATION,
                    confidence=sig.confidence,
                )
            )
        elif sig.id == ht.SIG_HOST_FROM_CLIENT:
            findings.append(
                Finding(
                    id="nginx.host_trust.http_host",
                    severity="medium",
                    title="Upstream Host header taken from client $http_host",
                    category="single_hop",
                    hop_ids=[hop_id],
                    based_on=[sig.id],
                    evidence=list(sig.evidence),
                    remediation=_REMEDIATION,
                    confidence=sig.confidence,
                )
            )
    return findings
