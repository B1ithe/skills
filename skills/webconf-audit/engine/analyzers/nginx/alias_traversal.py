"""gixy-parity: path traversal via alias in non-slash-terminated prefix locations."""
from __future__ import annotations

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.alias_traversal"
SIG_ALIAS = "location.alias.prefix_without_trailing_slash"


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    parents = astutil.index_parents(root)
    signals: list[Signal] = []

    for node in root.walk():
        if node.kind != "directive" or node.name != "alias" or not node.args:
            continue
        alias_path = node.args[0]
        loc = astutil.enclosing(node, parents, "location")
        if loc is None:
            continue
        mod, path = astutil.location_modifier_and_path(loc)
        # gixy: only non-strict prefix locations (no modifier or ^~)
        if mod not in (None, "^~"):
            continue
        if not path or path.endswith("/"):
            continue
        severity = "high" if alias_path.endswith("/") else "medium"
        signals.append(
            Signal(
                id=SIG_ALIAS,
                hop_id=hop_id,
                issuer=ISSUER,
                evidence=[
                    Evidence(file=node.file, line=node.line, snippet=astutil.snippet(node)),
                    Evidence(file=loc.file, line=loc.line, snippet=astutil.snippet(loc)),
                ],
                data={
                    "location": path,
                    "modifier": mod,
                    "alias": alias_path,
                    "severity": severity,
                },
            )
        )
    return signals
