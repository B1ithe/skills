"""gixy-parity: SSRF via controllable proxy_pass scheme/host."""
from __future__ import annotations

import re

from adapters.common.model import Node
from adapters.nginx.variables import NginxVarModel, build_var_model_from_ast, extract_vars
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.ssrf"
SIG_PROXY_PASS = "upstream.proxy_pass.user_controlled_authority"

_URI_RE = re.compile(r"(?P<scheme>[^?#/)]+://)?(?P<host>[^?#/)]+)")


def analyze(root: Node, *, hop_id: str, var_model: NginxVarModel | None = None) -> list[Signal]:
    model = var_model or build_var_model_from_ast(root)
    parents = astutil.index_parents(root)
    signals: list[Signal] = []

    for node in root.walk():
        if node.kind != "directive" or node.name != "proxy_pass" or not node.args:
            continue
        value = node.args[0]
        loc = astutil.enclosing(node, parents, "location")
        if loc is not None and astutil.has_internal(loc):
            continue

        parsed = _URI_RE.match(value)
        if not parsed:
            continue

        for part_name in ("scheme", "host"):
            part = parsed.group(part_name)
            if not part:
                continue
            bad = _risky_vars(part, model)
            if bad:
                signals.append(
                    Signal(
                        id=SIG_PROXY_PASS,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[
                            Evidence(
                                file=node.file,
                                line=node.line,
                                snippet=astutil.snippet(node),
                            )
                        ],
                        data={"directive": "proxy_pass", "script": value, "vars": bad, "part": part_name},
                    )
                )
                break
    return signals


def _risky_vars(script: str, model: NginxVarModel) -> list[str]:
    out: list[str] = []
    for v in extract_vars(script):
        if model.must_contain(v.name, "/"):
            # path-like → not an authority component we care about
            continue
        if model.can_contain(v.name, "."):
            out.append(v.name)
    return out
