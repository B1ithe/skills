from __future__ import annotations

from engine.analyzers.nginx import uri_injection as ui
from engine.model import Finding, Signal

_REMEDIATION = (
    "Avoid placing newline-capable variables ($uri / $document_uri / unsafe "
    "regex captures) into proxy_pass, proxy_set_header, add_header, or return. "
    "Prefer $request_uri, or proxy_pass without a URI part so the original "
    "request target is forwarded undecoded."
)

_MAP = {
    ui.SIG_REQUEST_LINE: (
        "nginx.http_splitting.upstream_request_line",
        "high",
        "HTTP splitting risk: decoded URI may enter upstream request-line",
    ),
    ui.SIG_REQUEST_HEADER: (
        "nginx.http_splitting.upstream_header",
        "high",
        "HTTP splitting risk: decoded URI may enter upstream request header",
    ),
    ui.SIG_REDIRECT: (
        "nginx.http_splitting.redirect",
        "high",
        "HTTP splitting / response splitting risk via return with decoded URI",
    ),
    ui.SIG_ADD_HEADER: (
        "nginx.http_splitting.response_header",
        "high",
        "HTTP response splitting risk: decoded URI in add_header",
    ),
}


def evaluate(signals: list[Signal], *, hop_id: str) -> list[Finding]:
    findings: list[Finding] = []
    for sig in signals:
        meta = _MAP.get(sig.id)
        if not meta:
            continue
        fid, severity, title = meta
        findings.append(
            Finding(
                id=fid,
                severity=severity,
                title=title,
                category="single_hop",
                hop_ids=[hop_id],
                based_on=[sig.id],
                evidence=list(sig.evidence),
                remediation=_REMEDIATION,
                confidence=sig.confidence,
                summary=(sig.data or {}).get("script"),
            )
        )
    return findings
