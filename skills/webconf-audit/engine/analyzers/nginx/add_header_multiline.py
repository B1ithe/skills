"""gixy-parity: multiline (folded) response headers via add_header / more_set_headers."""
from __future__ import annotations

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.add_header_multiline"
SIG_MULTILINE = "response.header.multiline_value"


def analyze(root: Node, *, hop_id: str, **_kwargs) -> list[Signal]:
    signals: list[Signal] = []
    for node in root.walk():
        if node.kind != "directive" or node.name not in {"add_header", "more_set_headers"}:
            continue
        for value in _header_values(node):
            if "\n " in value or "\n\t" in value:
                signals.append(
                    Signal(
                        id=SIG_MULTILINE,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=[
                            Evidence(file=node.file, line=node.line, snippet=astutil.snippet(node)[:200])
                        ],
                        data={"directive": node.name},
                    )
                )
                break
    return signals


def _header_values(node: Node) -> list[str]:
    if node.name == "add_header":
        return [node.args[1]] if len(node.args) >= 2 else []
    # more_set_headers: skip -s/-t options (headers-more module)
    result: list[str] = []
    skip_next = False
    for arg in node.args:
        if arg in {"-s", "-t"}:
            skip_next = True
        elif arg.startswith("-"):
            continue
        elif skip_next:
            skip_next = False
        else:
            result.append(arg)
    return result
