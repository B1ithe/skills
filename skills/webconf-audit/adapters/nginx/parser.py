from __future__ import annotations

from pathlib import Path

from pyparsing import ParseException, ParseResults

from adapters.base import ParseResult
from adapters.common.model import ConfigDocument, Node, block, comment, directive, include
from adapters.common.pathmap import resolve_include_pattern
from adapters.nginx.raw_parser import NginxRawParser

_HASH_LIKE = frozenset({"map", "types", "charset_map", "geo", "split_clients"})


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
        warnings: list[str],
        path_map: dict[str, str] | None,
        expand_includes: bool,
        current_file: Path | None = None,
        seen: set[str] | None = None,
    ) -> None:
        for item in parsed:
            name = item.get_name()
            if name == "comment":
                parent.children.append(comment(str(item[0]), file=file))
                continue
            if name == "include":
                inc_path = str(item[1])
                node = include(inc_path, file=file)
                parent.children.append(node)
                if expand_includes and current_file is not None and seen is not None:
                    matches = resolve_include_pattern(
                        inc_path, current_file=current_file, path_map=path_map
                    )
                    if not matches:
                        warnings.append(f"include not found: {inc_path} (from {current_file})")
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
                continue
            if name == "directive":
                toks = [str(x) for x in item]
                parent.children.append(directive(toks[0], toks[1:], file=file))
                continue
            if name == "block":
                keyword = str(item[0])
                args = [str(x) for x in item[1]]
                body = item[2]
                node = block(keyword, args, file=file)
                if keyword in _HASH_LIKE:
                    node.meta["hash_like"] = True
                    self._fill_hash_body(body, node, file=file, warnings=warnings)
                elif len(body):
                    self._fill(
                        body,
                        node,
                        file=file,
                        warnings=warnings,
                        path_map=path_map,
                        expand_includes=expand_includes,
                        current_file=current_file,
                        seen=seen,
                    )
                parent.children.append(node)
                continue
            if name == "hash_value":
                # Defensive: hash entries should normally be handled in _fill_hash_body.
                self._append_map_entry([str(x) for x in item], parent, file=file)
                continue
            warnings.append(f"unrecognized parse node in {file}: {name}")

    def _append_map_entry(self, hv_args: list[str], parent: Node, *, file: str) -> None:
        if not hv_args:
            return
        # Empty quoted keys ('' / "") are valid map matchers; keep them visible.
        key = hv_args[0] if hv_args[0] != "" else '""'
        parent.children.append(
            Node(kind="map_entry", name=key, args=list(hv_args[1:]), file=file)
        )

    def _fill_hash_body(self, body: ParseResults, parent: Node, *, file: str, warnings: list[str]) -> None:
        for hv in body:
            if not isinstance(hv, ParseResults):
                warnings.append(f"unexpected map/types entry in {file}")
                continue
            name = hv.get_name()
            if name == "comment":
                parent.children.append(comment(str(hv[0]), file=file))
                continue
            # Group(comment) wraps a comment ParseResults — detect nested comment.
            if len(hv) == 1 and isinstance(hv[0], ParseResults) and hv[0].get_name() == "comment":
                parent.children.append(comment(str(hv[0][0]), file=file))
                continue
            if name == "hash_value" or name is None:
                self._append_map_entry([str(x) for x in hv], parent, file=file)
                continue
            warnings.append(f"unexpected map/types entry kind {name!r} in {file}")
