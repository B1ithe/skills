from __future__ import annotations

from adapters.common.model import Node
from adapters.nginx.variables import build_var_model_from_ast
from engine.analyzers.nginx import (
    add_header_multiline,
    add_header_redefinition,
    alias_traversal,
    host_trust,
    origins,
    ssrf,
    uri_injection,
    valid_referers,
)
from engine.model import Signal

# gixy plugin parity
_ANALYZERS = (
    uri_injection,  # http_splitting
    host_trust,  # host_spoofing (Host $http_host / $arg_*)
    ssrf,
    origins,
    add_header_redefinition,
    add_header_multiline,
    valid_referers,
    alias_traversal,
)


def run_all(root: Node, *, hop_id: str) -> list[Signal]:
    model = build_var_model_from_ast(root)
    out: list[Signal] = []
    for mod in _ANALYZERS:
        out.extend(mod.analyze(root, hop_id=hop_id, var_model=model))
    return out
