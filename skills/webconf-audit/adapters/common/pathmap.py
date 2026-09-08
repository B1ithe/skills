from __future__ import annotations

import glob
from pathlib import Path


def apply_path_map(path: str, path_map: dict[str, str] | None) -> str:
    if not path_map:
        return path
    for src in sorted(path_map.keys(), key=len, reverse=True):
        dst = path_map[src]
        src_n = src.rstrip("/")
        if path == src or path == src_n or path.startswith(src_n + "/"):
            rel = path[len(src_n) :].lstrip("/")
            return str(Path(dst) / rel) if rel else dst
    return path


def resolve_include_pattern(
    pattern: str,
    *,
    current_file: Path,
    path_map: dict[str, str] | None,
) -> list[Path]:
    mapped = apply_path_map(pattern, path_map)
    candidates: list[Path] = []
    p = Path(mapped)
    if p.is_absolute():
        candidates.append(p)
    else:
        # nginx often resolves includes relative to the conf prefix, not only
        # the including file's directory (e.g. include stream.d/*.conf).
        candidates.append(current_file.parent / mapped)
        for root in (path_map or {}).values():
            candidates.append(Path(root) / mapped)

    found: list[Path] = []
    seen: set[str] = set()
    for cand in candidates:
        for match in glob.glob(str(cand)):
            mp = Path(match)
            if mp.is_file():
                key = str(mp.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(mp)
    return sorted(found)
