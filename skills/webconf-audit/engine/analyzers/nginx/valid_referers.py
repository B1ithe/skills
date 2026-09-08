"""gixy-parity: valid_referers includes 'none'."""
from __future__ import annotations

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.valid_referers"
SIG_NONE = "referer.valid_referers.includes_none"


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    signals: list[Signal] = []
    for node in root.walk():
        if node.kind != "directive" or node.name != "valid_referers":
            continue
        if "none" in node.args:
            signals.append(
                Signal(
                    id=SIG_NONE,
                    hop_id=hop_id,
                    issuer=ISSUER,
                    evidence=[Evidence(file=node.file, line=node.line, snippet=astutil.snippet(node))],
                    data={"args": list(node.args)},
                )
            )
    return signals
