from __future__ import annotations

from engine.analyzers.nginx import host_trust as ht
from engine.model import Finding, Signal

_REMEDIATION = (
    "Do not set the upstream Host header from client-controlled values such as "
    "$http_host or $arg_*. Prefer $host or a fixed server name."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    findings: list[Finding] = []
    for sig in signals:
        if sig.id != ht.SIG_HOST_FROM_CLIENT:
            continue
        script = (sig.data or {}).get("script") or ""
        title = (
            "Upstream Host header taken from client $http_host"
            if "http_host" in script
            else "Upstream Host header may be spoofed via request argument"
        )
        findings.append(
            Finding(
                id="nginx.host_spoofing.http_host",
                severity="medium",
                title=title,
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary=script or None,
            )
        )
    return findings
