from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


@dataclass
class Node:
    kind: str
    name: str = ""
    args: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    file: str | None = None
    line: int | None = None
    raw: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.name:
            d["name"] = self.name
        if self.args:
            d["args"] = list(self.args)
        if self.file:
            d["file"] = self.file
        if self.line is not None:
            d["line"] = self.line
        if self.raw is not None:
            d["raw"] = self.raw
        if self.meta:
            d["meta"] = dict(self.meta)
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def directive(name: str, args: Iterable[str] | None = None, **kw: Any) -> Node:
    return Node(kind="directive", name=name, args=list(args or []), **kw)


def block(name: str, args: Iterable[str] | None = None, children: Iterable[Node] | None = None, **kw: Any) -> Node:
    return Node(kind="block", name=name, args=list(args or []), children=list(children or []), **kw)


def include(path: str, **kw: Any) -> Node:
    return Node(kind="include", name="include", args=[path], **kw)


def comment(text: str, **kw: Any) -> Node:
    return Node(kind="comment", name="comment", args=[text], **kw)


@dataclass
class ConfigDocument:
    server: str
    root: Node
    entry_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "entry_file": self.entry_file,
            "root": self.root.to_dict(),
        }
