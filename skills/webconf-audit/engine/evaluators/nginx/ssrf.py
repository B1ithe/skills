from __future__ import annotations

from engine.analyzers.nginx import ssrf as az
from engine.model import Finding, Signal

_REMEDIATION = (
    "Do not let users control proxy_pass scheme/host. Use a fixed upstream, "
    "or restrict the location with `internal` and only reach it via trusted "
    "rewrites / error_page / X-Accel-Redirect."
)


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    out: list[Finding] = []
    for sig in signals:
        if sig.id != az.SIG_PROXY_PASS:
            continue
        vars_ = ", ".join((sig.data or {}).get("vars") or [])
        out.append(
            Finding(
                id="nginx.ssrf.proxy_pass",
                severity="high",
                title="Possible SSRF via user-controlled proxy_pass",
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary=f"controllable vars: {vars_}" if vars_ else None,
            )
        )
    return out
