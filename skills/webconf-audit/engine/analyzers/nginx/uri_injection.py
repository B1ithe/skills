from __future__ import annotations

"""Emit signals when newline-capable nginx vars flow into upstream sinks."""

from adapters.common.model import Node
from adapters.nginx.variables import NginxVarModel, build_var_model_from_ast
from engine.model import Evidence, Signal

ISSUER = "nginx.uri_injection"

# Semantic signal ids (no server prefix — combinable for chain rules later)
SIG_REQUEST_LINE = "upstream.request_line.includes_decoded_uri"
SIG_REQUEST_HEADER = "upstream.header.includes_decoded_uri"
SIG_REDIRECT = "response.redirect.includes_decoded_uri"
SIG_ADD_HEADER = "response.header.includes_decoded_uri"


def _ev(node: Node, snippet: str) -> Evidence:
    return Evidence(file=node.file, line=node.line, snippet=snippet)


def _script(args: list[str]) -> str:
    return " ".join(args)


def analyze(root: Node, *, hop_id: str, var_model: NginxVarModel | None = None) -> list[Signal]:
    model = var_model or build_var_model_from_ast(root)
    signals: list[Signal] = []

    for node in root.walk():
        if node.kind != "directive":
            continue
        name = node.name
        args = node.args
        if not args:
            continue

        if name == "proxy_pass":
            script = args[0]
            dangerous = model.dangerous_vars_in_script(script)
            if dangerous:
                signals.append(
                    Signal(
                        id=SIG_REQUEST_LINE,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[_ev(node, f"proxy_pass {_script(args)};")],
                        data={"directive": name, "vars": dangerous, "script": script},
                    )
                )
            continue

        if name == "proxy_set_header" and len(args) >= 2:
            header, script = args[0], args[1]
            dangerous = model.dangerous_vars_in_script(script)
            if dangerous:
                signals.append(
                    Signal(
                        id=SIG_REQUEST_HEADER,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[_ev(node, f"proxy_set_header {_script(args)};")],
                        data={
                            "directive": name,
                            "header": header,
                            "vars": dangerous,
                            "script": script,
                        },
                    )
                )
            continue

        if name == "add_header" and len(args) >= 2:
            script = args[1]
            dangerous = model.dangerous_vars_in_script(script)
            if dangerous:
                signals.append(
                    Signal(
                        id=SIG_ADD_HEADER,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[_ev(node, f"add_header {_script(args)};")],
                        data={"directive": name, "vars": dangerous, "script": script},
                    )
                )
            continue

        if name == "return" and args:
            # return 302 http://x$uri;  or return $uri;
            script = _script(args)
            dangerous = model.dangerous_vars_in_script(script)
            if dangerous:
                signals.append(
                    Signal(
                        id=SIG_REDIRECT,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[_ev(node, f"return {_script(args)};")],
                        data={"directive": name, "vars": dangerous, "script": script},
                    )
                )
            continue

        if name == "rewrite" and len(args) >= 2:
            # rewrite regex replacement flags;
            replacement = args[1]
            dangerous = model.dangerous_vars_in_script(replacement)
            # Also: if replacement uses $uri explicitly
            if dangerous:
                signals.append(
                    Signal(
                        id=SIG_REQUEST_LINE,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[_ev(node, f"rewrite {_script(args)};")],
                        data={"directive": name, "vars": dangerous, "script": replacement},
                    )
                )
            continue

    return _dedupe(signals)


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[tuple] = set()
    out: list[Signal] = []
    for s in signals:
        key = (s.id, s.evidence[0].file if s.evidence else None, s.evidence[0].snippet if s.evidence else None)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
