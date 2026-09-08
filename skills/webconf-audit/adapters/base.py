from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from adapters.common.model import ConfigDocument


@dataclass
class ParseResult:
    server: str
    document: ConfigDocument
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "warnings": self.warnings,
            "meta": self.meta,
            "document": self.document.to_dict(),
        }


class Adapter(Protocol):
    name: str

    def parse_file(self, path: str | Path, *, path_map: dict[str, str] | None = None) -> ParseResult: ...

    def parse_text(self, text: str, *, path_info: str = "<string>") -> ParseResult: ...


def get_adapter(server: str) -> Adapter:
    key = server.lower().strip()
    if key in ("nginx", "ngx"):
        from adapters.nginx.parser import NginxAdapter

        return NginxAdapter()
    if key in ("apache", "httpd"):
        from adapters.apache.parser import ApacheAdapter

        return ApacheAdapter()
    raise ValueError(f"unsupported server adapter: {server!r} (supported: nginx, apache)")
