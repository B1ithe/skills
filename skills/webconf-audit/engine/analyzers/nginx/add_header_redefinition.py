"""gixy-parity: nested add_header drops parent security headers."""
from __future__ import annotations

from adapters.common.model import Node
from engine.analyzers.nginx import astutil
from engine.model import Evidence, Signal

ISSUER = "nginx.add_header_redefinition"
SIG_DROPPED = "response.add_header.parent_headers_dropped"

# gixy default interesting headers (lowercase)
DEFAULT_HEADERS = frozenset(
    {
        "x-frame-options",
        "x-content-type-options",
        "x-xss-protection",
        "content-security-policy",
        "cache-control",
        "strict-transport-security",
    }
)


def analyze(
    root: Node,
    *,
    hop_id: str,
    interesting_headers: frozenset[str] | set[str] | None = None,
    **_kwargs,
) -> list[Signal]:
    interesting = {h.lower() for h in (interesting_headers or DEFAULT_HEADERS)}
    parents = astutil.index_parents(root)
    signals: list[Signal] = []

    for node in root.walk():
        if node.kind != "block" or node.name not in {"server", "location", "if"}:
            continue
        child_headers = _header_names(node)
        if not child_headers:
            continue
        # Nearest parent that also defines add_header (gixy: first parent with headers)
        for parent in astutil.ancestors(node, parents):
            if parent.kind != "block":
                continue
            parent_headers = _header_names(parent)
            if not parent_headers:
                continue
            dropped = (parent_headers - child_headers) & interesting
            if dropped:
                evidence = [
                    Evidence(file=d.file, line=d.line, snippet=astutil.snippet(d))
                    for d in astutil.direct_directives(parent, "add_header")
                    + astutil.direct_directives(node, "add_header")
                ]
                signals.append(
                    Signal(
                        id=SIG_DROPPED,
                        hop_id=hop_id,
                        issuer=ISSUER,
                        evidence=evidence,
                        data={
                            "scope": node.name,
                            "dropped": sorted(dropped),
                            "parent_headers": sorted(parent_headers),
                            "child_headers": sorted(child_headers),
                        },
                    )
                )
            break
    return signals


def _header_names(block: Node) -> set[str]:
    names: set[str] = set()
    for d in astutil.direct_directives(block, "add_header"):
        if d.args:
            names.add(d.args[0].lower())
    return names
