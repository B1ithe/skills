from __future__ import annotations

"""Emit signals for gixy-style Host header spoofing via proxy_set_header.

Only covers web-server-layer cases (Host $http_host / $arg_*).
Client X-Forwarded-Host trust is treated as an application concern and is
intentionally not reported.
"""

from adapters.common.model import Node
from engine.model import Evidence, Signal

ISSUER = "nginx.host_spoofing"
SIG_HOST_FROM_CLIENT = "client.host.trusted_as_upstream_host"


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    signals: list[Signal] = []
    for node in root.walk():
        if node.kind != "directive" or node.name != "proxy_set_header" or len(node.args) < 2:
            continue
        header, value = node.args[0], node.args[1]
        if header.lower() != "host":
            continue
        # gixy host_spoofing: Host $http_host or Host $arg_*
        if value in ("$http_host", "${http_host}") or value.startswith("$arg_") or value.startswith(
            "${arg_"
        ):
            snippet = f"proxy_set_header {' '.join(node.args)};"
            signals.append(
                Signal(
                    id=SIG_HOST_FROM_CLIENT,
                    hop_id=hop_id,
                    issuer=ISSUER,
                    evidence=[Evidence(file=node.file, line=node.line, snippet=snippet)],
                    data={"header": header, "script": value},
                )
            )
    return signals
