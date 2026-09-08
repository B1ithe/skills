from __future__ import annotations

from adapters.common.model import Node
from adapters.nginx.variables import build_var_model_from_ast
from engine.analyzers.nginx import host_trust, uri_injection
from engine.model import Signal


def run_all(root: Node, *, hop_id: str) -> list[Signal]:
    model = build_var_model_from_ast(root)
    out: list[Signal] = []
    out.extend(uri_injection.analyze(root, hop_id=hop_id, var_model=model))
    out.extend(host_trust.analyze(root, hop_id=hop_id))
    return out
