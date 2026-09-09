"""Signal: nginx reverse-proxies to an HTTP upstream (candidate for chain).

Used by path-confusion chain rules when the upstream is Apache: nginx
URL-decodes then normalizes, while Apache ≥2.4.49 normalizes before decoding
`%2f`, so the same request path can map to different resources.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.proxy_to_upstream"
SIG_HTTP_PROXY = "upstream.proxy.http_reverse_proxy"

# nginx upstream{} names — not stream-style host:port bare forms
_UPSTREAM_NAME = re.compile(r"^[A-Za-z_][\w]*$")


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    parents = astutil.index_parents(root)
    signals: list[Signal] = []
    # Dedupe identical location+url pairs (includes may repeat), keep distinct routes.
    seen: set[tuple[str | None, str]] = set()

    for node in root.walk():
        if node.kind != "directive" or node.name != "proxy_pass" or not node.args:
            continue
        # stream { proxy_pass host:port; } is not an HTTP reverse-proxy to Apache
        if astutil.enclosing(node, parents, "stream") is not None:
            continue
        url = node.args[0]
        # Scripted upstreams ($uri / $request_uri / $host) are out of scope for
        # authority matching; chain needs a resolvable HTTP target.
        if "$" in url:
            continue
        if url.startswith("http://") or url.startswith("https://"):
            if "unix:" in url:
                continue
            authority = _authority(url)
        else:
            # bare upstream{} name only (not 127.0.0.1:port stream syntax)
            if not _UPSTREAM_NAME.match(url):
                continue
            authority = url

        loc = astutil.enclosing(node, parents, "location")
        loc_path = None
        if loc is not None:
            _mod, loc_path = astutil.location_modifier_and_path(loc)

        key = (loc_path, url)
        if key in seen:
            continue
        seen.add(key)

        evidence = [Evidence(file=node.file, line=node.line, snippet=astutil.snippet(node))]
        if loc is not None:
            evidence.insert(0, Evidence(file=loc.file, line=loc.line, snippet=astutil.snippet(loc)))

        signals.append(
            Signal(
                id=SIG_HTTP_PROXY,
                hop_id=hop_id,
                issuer=ISSUER,
                evidence=evidence,
                data={
                    "location": loc_path,
                    "proxy_pass": url,
                    "upstream_authority": authority,
                },
            )
        )
    return signals


def _authority(url: str) -> str | None:
    if url.startswith("http://unix:") or url.startswith("https://unix:"):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.hostname:
        if parts.port:
            return f"{parts.hostname}:{parts.port}"
        return parts.hostname
    return url
