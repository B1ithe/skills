"""Chain: nginx reverse-proxy → Apache path decode/normalize mismatch.

nginx: decode (%2f → /) then normalize
Apache < 2.4.49: often 404 on %2f in the path
Apache ≥ 2.4.49: normalize first, then decode — so
  /a/b/..%2f/../index.html
  may become /index.html on nginx's view of routing vs /a/b/index.html on Apache.

Policy: if the pipeline pairs nginx with an Apache origin that the edge
actually proxy_pass'es to, emit this chain risk (no need for a specific
location/proxy_pass shape beyond "HTTP reverse proxy to that Apache").
"""
from __future__ import annotations

from engine.analyzers.nginx import proxy_prefix as pp
from engine.model import Evidence, Finding, HopResult

_REMEDIATION = (
    "Do not assume nginx and Apache see the same path for encoded segments. "
    "Reject suspicious encodings at the edge, align path allowlists on both "
    "hops, or avoid relying on path equivalence across the reverse proxy."
)

# Version-scoped behavior for this chain defect.
_AFFECTED_VERSIONS = [
    {
        "component": "nginx",
        "versions": "*",
        "note": "URL-decode first, then normalize (e.g. .. and /).",
    },
    {
        "component": "apache",
        "versions": "<2.4.49",
        "note": "Path containing %2f often results in 404 (no differential hit).",
    },
    {
        "component": "apache",
        "versions": ">=2.4.49",
        "note": (
            "Normalize before decoding %2f; "
            "/a/b/..%2f/../index.html can resolve to /a/b/index.html while "
            "nginx's decode-then-normalize view can be /index.html."
        ),
    },
]


def evaluate(hops: list[HopResult]) -> list[Finding]:
    findings: list[Finding] = []
    nginx_hops = [h for h in hops if h.hop.kind == "nginx"]
    apache_hops = [h for h in hops if h.hop.kind in ("apache", "httpd")]
    if not nginx_hops or not apache_hops:
        return findings

    for edge in nginx_hops:
        proxy_signals = [s for s in edge.signals if s.id == pp.SIG_HTTP_PROXY]
        if not proxy_signals:
            continue
        for origin in apache_hops:
            listen = list(origin.behaviors.get("listen_addrs") or [])
            matched = [s for s in proxy_signals if _targets_origin(s.data.get("upstream_authority"), listen)]
            if not matched:
                # User explicitly paired apache, but no proxy_pass authority matched
                # Listen (e.g. only unix sockets). Skip rather than over-report.
                continue

            # One finding per nginx→apache pair (not per location), with evidence
            # from matching proxy_pass sites (cap snippets).
            evidence: list[Evidence] = []
            routes: list[str] = []
            for sig in matched[:8]:
                evidence.extend(sig.evidence)
                loc = (sig.data or {}).get("location")
                upstream = (sig.data or {}).get("proxy_pass")
                routes.append(f"{loc or '?'} → {upstream}")

            findings.append(
                Finding(
                    id="chain.path_confusion.nginx_apache_decode_normalize",
                    severity="high",
                    title="Path decode/normalize mismatch: nginx reverse-proxy to Apache",
                    category="chain",
                    hop_ids=[edge.hop.id, origin.hop.id],
                    based_on=[pp.SIG_HTTP_PROXY],
                    evidence=evidence[:12],
                    remediation=_REMEDIATION,
                    confidence="high",
                    affected_versions=list(_AFFECTED_VERSIONS),
                    summary=(
                        "Differential path mapping when nginx fronts Apache. "
                        f"Routes: {'; '.join(routes[:5])}"
                        + (f" (+{len(routes) - 5} more)" if len(routes) > 5 else "")
                        + (
                            f"; Apache listens {', '.join(listen)}"
                            if listen
                            else ""
                        )
                    ),
                )
            )
    return findings


def _targets_origin(authority: str | None, listen_addrs: list[str]) -> bool:
    """Match proxy_pass authority to Apache Listen when possible."""
    if authority is None:
        # Dynamic proxy_pass ($var) — only claim match if Listen unknown and
        # user still paired hops? Prefer false to avoid noise.
        return False
    # unix sockets are not this Apache httpd Listen
    if "unix:" in authority:
        return False
    if not listen_addrs:
        # Paired apache hop without parsed Listen → accept non-unix HTTP targets
        return True

    auth = authority.lower()
    for addr in listen_addrs:
        a = addr.lower()
        if auth == a:
            return True
        if ":" in auth and ":" in a:
            aport = auth.rsplit(":", 1)[-1]
            lport = a.rsplit(":", 1)[-1]
            if aport == lport:
                host = auth.rsplit(":", 1)[0]
                lhost = a.rsplit(":", 1)[0]
                locals_ = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::]", "[::1]"}
                if host in locals_ or lhost in locals_ or host == lhost:
                    return True
    return False
