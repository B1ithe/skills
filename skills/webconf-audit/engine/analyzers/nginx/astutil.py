#!/usr/bin/env python3
"""AST helpers for nginx rule analyzers (parent links, location shape, etc.)."""
from __future__ import annotations

from adapters.common.model import Node


def index_parents(root: Node) -> dict[int, Node | None]:
    parents: dict[int, Node | None] = {id(root): None}

    def walk(node: Node) -> None:
        for child in node.children:
            parents[id(child)] = node
            walk(child)

    walk(root)
    return parents


def ancestors(node: Node, parents: dict[int, Node | None]) -> list[Node]:
    out: list[Node] = []
    cur = parents.get(id(node))
    while cur is not None:
        out.append(cur)
        cur = parents.get(id(cur))
    return out


def enclosing(node: Node, parents: dict[int, Node | None], name: str) -> Node | None:
    for a in ancestors(node, parents):
        if a.kind == "block" and a.name == name:
            return a
    return None


def location_modifier_and_path(loc: Node) -> tuple[str | None, str | None]:
    """Return (modifier, path) for a location block."""
    args = loc.args or []
    if not args:
        return None, None
    if args[0] in ("=", "~", "~*", "^~"):
        return args[0], args[1] if len(args) > 1 else None
    return None, args[0]


def direct_directives(block: Node, name: str) -> list[Node]:
    """Directives named `name` that are direct children of block (not nested)."""
    return [c for c in block.children if c.kind == "directive" and c.name == name]


def has_internal(block: Node) -> bool:
    return any(c.kind == "directive" and c.name == "internal" for c in block.children)


def snippet(node: Node) -> str:
    if node.kind == "directive":
        return f"{node.name} {' '.join(node.args)};".strip()
    if node.kind == "block":
        args = " ".join(node.args)
        return f"{node.name} {args}".strip() + " {"
    return node.name
