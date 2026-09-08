from __future__ import annotations

from pathlib import Path

from adapters.apache.raw_parser import RawToken, tokenize_apache
from adapters.base import ParseResult
from adapters.common.model import ConfigDocument, Node, block, comment, directive, include
from adapters.common.pathmap import resolve_include_pattern


class ApacheAdapter:
    name = "apache"

    def parse_text(self, text: str, *, path_info: str = "<string>") -> ParseResult:
        warnings: list[str] = []
        root = block("root", file=path_info, line=1)
        self._build(tokenize_apache(text), root, file=path_info, warnings=warnings)
        return ParseResult(
            server=self.name,
            document=ConfigDocument(server=self.name, root=root, entry_file=path_info),
            warnings=warnings,
        )

    def parse_file(self, path: str | Path, *, path_map: dict[str, str] | None = None) -> ParseResult:
        path = Path(path).resolve()
        warnings: list[str] = []
        seen: set[str] = set()
        root = block("root", file=str(path), line=1)
        self._parse_file_into(path, root, path_map=path_map or {}, warnings=warnings, seen=seen)
        return ParseResult(
            server=self.name,
            document=ConfigDocument(server=self.name, root=root, entry_file=str(path)),
            warnings=warnings,
            meta={"files_parsed": sorted(seen)},
        )

    def _parse_file_into(
        self,
        path: Path,
        parent: Node,
        *,
        path_map: dict[str, str],
        warnings: list[str],
        seen: set[str],
    ) -> None:
        key = str(path.resolve())
        if key in seen:
            warnings.append(f"skip circular include: {key}")
            return
        seen.add(key)
        tokens = tokenize_apache(path.read_text(encoding="utf-8", errors="replace"))
        self._build(
            tokens,
            parent,
            file=str(path),
            warnings=warnings,
            path_map=path_map,
            expand_includes=True,
            current_file=path,
            seen=seen,
        )

    def _build(
        self,
        tokens: list[RawToken],
        parent: Node,
        *,
        file: str,
        warnings: list[str],
        path_map: dict[str, str] | None = None,
        expand_includes: bool = False,
        current_file: Path | None = None,
        seen: set[str] | None = None,
        start: int = 0,
        stop_name: str | None = None,
    ) -> int:
        i = start
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind == "section_close":
                if stop_name is None:
                    warnings.append(f"{file}:{tok.line}: unexpected </{tok.name}>")
                    i += 1
                    continue
                if tok.name.lower() != stop_name.lower():
                    warnings.append(
                        f"{file}:{tok.line}: expected </{stop_name}> but saw </{tok.name}>"
                    )
                return i + 1
            if tok.kind == "comment":
                parent.children.append(
                    comment(tok.args[0] if tok.args else "", file=file, line=tok.line, raw=tok.raw)
                )
                i += 1
                continue
            if tok.kind == "include":
                node = include(tok.args[0], file=file, line=tok.line, raw=tok.raw)
                node.meta["directive"] = tok.name
                parent.children.append(node)
                if expand_includes and current_file is not None and seen is not None:
                    matches = resolve_include_pattern(
                        tok.args[0], current_file=current_file, path_map=path_map
                    )
                    if not matches and tok.name.lower() != "includeoptional":
                        warnings.append(f"include not found: {tok.args[0]} (from {current_file})")
                    for match in matches:
                        child_root = block("included", args=[str(match)], file=str(match))
                        node.children.append(child_root)
                        self._parse_file_into(
                            match,
                            child_root,
                            path_map=path_map or {},
                            warnings=warnings,
                            seen=seen,
                        )
                i += 1
                continue
            if tok.kind == "directive":
                parent.children.append(
                    directive(tok.name, tok.args, file=file, line=tok.line, raw=tok.raw)
                )
                i += 1
                continue
            if tok.kind == "section_open":
                node = block(tok.name, tok.args, file=file, line=tok.line, raw=tok.raw)
                node.meta["section"] = True
                parent.children.append(node)
                i = self._build(
                    tokens,
                    node,
                    file=file,
                    warnings=warnings,
                    path_map=path_map,
                    expand_includes=expand_includes,
                    current_file=current_file,
                    seen=seen,
                    start=i + 1,
                    stop_name=tok.name,
                )
                continue
            warnings.append(f"{file}:{tok.line}: unknown token kind {tok.kind}")
            i += 1
        if stop_name is not None:
            warnings.append(f"{file}: unclosed <{stop_name}> section")
        return i
