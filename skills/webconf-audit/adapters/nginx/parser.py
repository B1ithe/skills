from __future__ import annotations

from pathlib import Path

from pyparsing import ParseException, ParseResults, lineno

from adapters.base import ParseResult
from adapters.common.model import ConfigDocument, Node, block, comment, directive, include
from adapters.common.pathmap import resolve_include_pattern
from adapters.nginx.raw_parser import NginxRawParser

_HASH_LIKE = frozenset({"map", "types", "charset_map", "geo", "split_clients"})


def _line_at(loc: int | None, source: str) -> int | None:
    if loc is None or not source:
        return None
    # Located may start on skipped whitespace/newline; advance to content.
    i = loc
    n = len(source)
    while i < n and source[i] in " \t\r\n":
        i += 1
    if i >= n:
        i = min(loc, n - 1)
    return lineno(i, source)


def _unwrap_located(item: ParseResults, source: str) -> tuple[ParseResults, int | None]:
    """Return (inner named results, 1-based line) from a Located-wrapped Group item."""
    if "locn_start" in item and "value" in item:
        return item["value"], _line_at(item["locn_start"], source)
    return item, None


class NginxAdapter:
    name = "nginx"

    def __init__(self) -> None:
        self._raw = NginxRawParser()

    def parse_text(self, text: str, *, path_info: str = "<string>") -> ParseResult:
        warnings: list[str] = []
        root = block("root", file=path_info, line=1)
        parsed = self._parse_raw(text, path_info)
        self._fill(
            parsed,
            root,
            file=path_info,
            source=text,
            warnings=warnings,
            path_map=None,
            expand_includes=False,
        )
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

    def _parse_raw(self, text: str, path_info: str) -> ParseResults:
        try:
            return self._raw.parse(text)
        except ParseException as exc:
            raise ValueError(
                f"nginx parse failed in {path_info}: char {exc.loc} "
                f"(line {exc.lineno}, col {exc.column})"
            ) from exc

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
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = self._parse_raw(text, str(path))
        self._fill(
            parsed,
            parent,
            file=str(path),
            source=text,
            warnings=warnings,
            path_map=path_map,
            expand_includes=True,
            current_file=path,
            seen=seen,
        )

    def _fill(
        self,
        parsed: ParseResults,
        parent: Node,
        *,
        file: str,
        source: str,
        warnings: list[str],
        path_map: dict[str, str] | None,
        expand_includes: bool,
        current_file: Path | None = None,
        seen: set[str] | None = None,
    ) -> None:
        for item in parsed:
            inner, line = _unwrap_located(item, source)
            name = inner.get_name()
            if name == "comment":
                parent.children.append(comment(str(inner[0]), file=file, line=line))
                continue
            if name == "include":
                inc_path = str(inner[1])
                node = include(inc_path, file=file, line=line)
                parent.children.append(node)
                if expand_includes and current_file is not None and seen is not None:
                    matches = resolve_include_pattern(
                        inc_path, current_file=current_file, path_map=path_map
                    )
                    if not matches:
                        warnings.append(f"include not found: {inc_path} (from {current_file})")
                    for match in matches:
                        child_root = block("included", args=[str(match)], file=str(match), line=1)
                        node.children.append(child_root)
                        self._parse_file_into(
                            match,
                            child_root,
                            path_map=path_map or {},
                            warnings=warnings,
                            seen=seen,
                        )
                continue
            if name == "directive":
                toks = [str(x) for x in inner]
                parent.children.append(directive(toks[0], toks[1:], file=file, line=line))
                continue
            if name == "block":
                keyword = str(inner[0])
                args = [str(x) for x in inner[1]]
                body = inner[2]
                node = block(keyword, args, file=file, line=line)
                if keyword in _HASH_LIKE:
                    node.meta["hash_like"] = True
                    self._fill_hash_body(body, node, file=file, source=source, warnings=warnings)
                elif len(body):
                    self._fill(
                        body,
                        node,
                        file=file,
                        source=source,
                        warnings=warnings,
                        path_map=path_map,
                        expand_includes=expand_includes,
                        current_file=current_file,
                        seen=seen,
                    )
                parent.children.append(node)
                continue
            if name == "hash_value":
                self._append_map_entry([str(x) for x in inner], parent, file=file, line=line)
                continue
            warnings.append(f"unrecognized parse node in {file}: {name}")

    def _append_map_entry(
        self, hv_args: list[str], parent: Node, *, file: str, line: int | None = None
    ) -> None:
        if not hv_args:
            return
        key = hv_args[0] if hv_args[0] != "" else '""'
        parent.children.append(
            Node(kind="map_entry", name=key, args=list(hv_args[1:]), file=file, line=line)
        )

    def _fill_hash_body(
        self, body: ParseResults, parent: Node, *, file: str, source: str, warnings: list[str]
    ) -> None:
        for hv in body:
            if not isinstance(hv, ParseResults):
                warnings.append(f"unexpected map/types entry in {file}")
                continue
            inner, line = _unwrap_located(hv, source)
            name = inner.get_name()
            if name == "comment":
                parent.children.append(comment(str(inner[0]), file=file, line=line))
                continue
            if name == "hash_value":
                self._append_map_entry([str(x) for x in inner], parent, file=file, line=line)
                continue
            warnings.append(f"unexpected map/types entry kind {name!r} in {file}")
