from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from note_common import maintained_notes, parse_frontmatter, relative_posix

IGNORED_RAW_NAMES = {".DS_Store", "README.md"}


@dataclass(frozen=True)
class SourceRegistration:
    path: str
    sha256: str | None
    note_page: str
    note_file: Path


@dataclass(frozen=True)
class SourceStatus:
    path: str
    kind: str
    status: str
    registered: bool
    changed: bool
    current_sha256: str | None
    registered_sha256: str | None
    note_page: str | None
    note_pages: list[str]
    asset_dir: str | None
    asset_dir_exists: bool | None

    def to_dict(self) -> dict[str, object]:
        item: dict[str, object] = {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.current_sha256,
            "status": self.status,
            "registered": self.registered,
            "changed": self.changed,
            "current_sha256": self.current_sha256,
            "registered_sha256": self.registered_sha256,
            "note_page": self.note_page,
        }
        if len(self.note_pages) > 1:
            item["note_pages"] = self.note_pages
        if self.asset_dir is not None:
            item["asset_dir"] = self.asset_dir
            item["asset_dir_exists"] = bool(self.asset_dir_exists)
        return item


def raw_root(vault: Path) -> Path:
    return vault / "RAW"


def clippings_root(vault: Path) -> Path:
    return raw_root(vault) / "Clippings"


def clipping_assets_root(vault: Path) -> Path:
    return clippings_root(vault) / "assets"


def ai_saves_root(vault: Path) -> Path:
    return raw_root(vault) / "AiSaves"


def ai_save_assets_root(vault: Path) -> Path:
    return ai_saves_root(vault) / "assets"


def is_raw_inventory_file(path: Path, vault: Path) -> bool:
    raw = raw_root(vault)
    clipping_assets = clipping_assets_root(vault)
    ai_save_assets = ai_save_assets_root(vault)
    try:
        relative = path.relative_to(raw)
    except ValueError:
        return False
    if any(part.startswith(".") for part in relative.parts):
        return False
    if path.name in IGNORED_RAW_NAMES:
        return False
    if path == clipping_assets or clipping_assets in path.parents:
        return False
    if path == ai_save_assets or ai_save_assets in path.parents:
        return False
    return path.is_file()


def iter_raw_files(vault: Path) -> list[Path]:
    raw = raw_root(vault)
    if not raw.exists():
        return []
    return sorted(
        path for path in raw.rglob("*") if is_raw_inventory_file(path, vault)
    )


def clipping_notes(vault: Path) -> list[Path]:
    clippings = clippings_root(vault)
    if not clippings.exists():
        return []
    return sorted(
        path
        for path in clippings.glob("*.md")
        if path.is_file() and path.name != "README.md"
    )


def ai_saved_pages(vault: Path) -> list[Path]:
    saves = ai_saves_root(vault)
    if not saves.exists():
        return []
    return sorted(
        path
        for path in saves.glob("*.md")
        if path.is_file() and path.name != "README.md"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_source_registry(vault: Path) -> dict[str, list[SourceRegistration]]:
    registry: dict[str, list[SourceRegistration]] = {}
    for note_file in maintained_notes(vault):
        fields, errors = parse_frontmatter(note_file.read_text(encoding="utf-8"))
        if errors:
            continue
        sources = fields.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_path = source.get("path")
            if not isinstance(source_path, str) or not source_path:
                continue
            sha = source.get("sha256")
            registry.setdefault(source_path, []).append(
                SourceRegistration(
                    path=source_path,
                    sha256=sha if isinstance(sha, str) else None,
                    note_page=relative_posix(note_file, vault),
                    note_file=note_file,
                )
            )
    return registry


def classify_source_path(path: Path, vault: Path) -> tuple[str, Path | None]:
    if path.parent == clippings_root(vault):
        return "clipping", clipping_assets_root(vault) / path.stem
    if path.parent == ai_saves_root(vault):
        return "ai-save", ai_save_assets_root(vault) / path.stem
    return "raw", None


def classify_source_relative(source_path: str, vault: Path) -> tuple[str, Path | None]:
    path = vault.joinpath(*PurePosixPath(source_path).parts)
    return classify_source_path(path, vault)


def _status_for(
    relative: str,
    vault: Path,
    registry: dict[str, list[SourceRegistration]],
    raw_by_path: dict[str, Path],
) -> SourceStatus:
    records = registry.get(relative, [])
    raw_file = raw_by_path.get(relative)
    current_sha = sha256(raw_file) if raw_file is not None else None
    registered_sha = records[0].sha256 if records else None
    note_pages = [record.note_page for record in records]
    note_page = note_pages[0] if note_pages else None

    if len(records) > 1:
        status = "duplicate"
    elif raw_file is None and records:
        status = "missing"
    elif not records:
        status = "new"
    elif registered_sha == current_sha:
        status = "current"
    else:
        status = "changed"

    kind, asset_dir = (
        classify_source_path(raw_file, vault)
        if raw_file is not None
        else classify_source_relative(relative, vault)
    )
    return SourceStatus(
        path=relative,
        kind=kind,
        status=status,
        registered=bool(records),
        changed=status == "changed",
        current_sha256=current_sha,
        registered_sha256=registered_sha,
        note_page=note_page,
        note_pages=note_pages,
        asset_dir=relative_posix(asset_dir, vault) if asset_dir is not None else None,
        asset_dir_exists=asset_dir.exists() if asset_dir is not None else None,
    )


def inventory_sources(vault: Path) -> list[SourceStatus]:
    raw_by_path = {
        relative_posix(path, vault): path
        for path in iter_raw_files(vault)
    }
    registry = collect_source_registry(vault)
    paths = sorted(set(raw_by_path) | set(registry))
    return [
        _status_for(path, vault, registry, raw_by_path)
        for path in paths
    ]


def source_health_errors(vault: Path) -> list[str]:
    errors: list[str] = []
    for item in inventory_sources(vault):
        if item.status == "duplicate":
            errors.append(
                f"duplicate source path {item.path}: "
                f"{', '.join(item.note_pages)}"
            )
        elif item.status == "missing":
            errors.append(
                f"missing source path {item.path}: "
                f"{', '.join(item.note_pages)}"
            )
        elif item.status == "changed":
            errors.append(
                f"source changed {item.path}: registered sha256 "
                f"{item.registered_sha256}, current sha256 {item.current_sha256} "
                f"({item.note_page})"
            )
    return errors


def update_frontmatter_sources(
    fields: dict[str, object],
    path_updates: dict[str, str],
) -> bool:
    changed = False
    sources = fields.get("sources")
    if not isinstance(sources, list):
        return False
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_path = source.get("path")
        if isinstance(source_path, str) and source_path in path_updates:
            source["path"] = path_updates[source_path]
            changed = True
    return changed
