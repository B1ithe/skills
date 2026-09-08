from __future__ import annotations

from adapters.common.model import Node
from engine.model import Evidence, Signal

ISSUER = "nginx.host_trust"
SIG_FORWARDED_HOST = "client.forwarded_host.trusted_as_authority"
SIG_HOST_FROM_CLIENT = "client.host.trusted_as_upstream_host"


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    signals: list[Signal] = []
    for node in root.walk():
        if node.kind != "directive" or node.name != "proxy_set_header" or len(node.args) < 2:
            continue
        header, value = node.args[0], node.args[1]
        snippet = f"proxy_set_header {' '.join(node.args)};"
        ev = Evidence(file=node.file, line=node.line, snippet=snippet)
        # $x_f_h comes from map of X-Forwarded-Host / Host — client influenced
        if "$x_f_h" in value or "x_f_h" in value:
            signals.append(
                Signal(
                    id=SIG_FORWARDED_HOST,
                    hop_id=hop_id,
                    issuer=ISSUER,
                    evidence=[ev],
                    data={"header": header, "script": value},
                )
            )
        # gixy host_spoofing: Host $http_host or Host $arg_*
        if header.lower() != "host":
            continue
        if value in ("$http_host", "${http_host}") or value.startswith("$arg_") or value.startswith("${arg_"):
            signals.append(
                Signal(
                    id=SIG_HOST_FROM_CLIENT,
                    hop_id=hop_id,
                    issuer=ISSUER,
                    evidence=[ev],
                    data={"header": header, "script": value},
                )
            )
    return signals
