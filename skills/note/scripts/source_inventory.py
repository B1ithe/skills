#!/usr/bin/env python3
"""Read-only inventory for local raw source material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from note_common import maintained_notes, parse_frontmatter, vault_root

DEFAULT_ROOT = Path(os.environ.get("LLM_NOTE_ROOT", "."))
VAULT = vault_root(DEFAULT_ROOT)
IGNORED_NAMES = {".DS_Store", "README.md"}


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


def is_ignored(path: Path, vault: Path | None = None) -> bool:
    vault = vault or VAULT
    raw = raw_root(vault)
    clipping_assets = clipping_assets_root(vault)
    ai_save_assets = ai_save_assets_root(vault)
    if any(part.startswith(".") for part in path.relative_to(raw).parts):
        return True
    if path.name in IGNORED_NAMES:
        return True
    if path == clipping_assets or clipping_assets in path.parents:
        return True
    if path == ai_save_assets or ai_save_assets in path.parents:
        return True
    return False


def iter_raw_files(vault: Path | None = None) -> list[Path]:
    vault = vault or VAULT
    raw = raw_root(vault)
    if not raw.exists():
        return []
    return sorted(
        path
        for path in raw.rglob("*")
        if path.is_file() and not is_ignored(path, vault)
    )


def clipping_notes(vault: Path | None = None) -> list[Path]:
    vault = vault or VAULT
    clippings = clippings_root(vault)
    if not clippings.exists():
        return []
    return sorted(
        path
        for path in clippings.glob("*.md")
        if path.is_file() and path.name != "README.md"
    )


def ai_saved_pages(vault: Path | None = None) -> list[Path]:
    vault = vault or VAULT
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


def note_pages(vault: Path | None = None) -> list[Path]:
    return maintained_notes(vault or VAULT)


def note_registry(
    vault: Path | None = None,
) -> dict[str, list[dict[str, str | None]]]:
    vault = vault or VAULT
    registry: dict[str, list[dict[str, str | None]]] = {}
    for path in note_pages(vault):
        fields, errors = parse_frontmatter(path.read_text(encoding="utf-8"))
        if errors:
            continue
        sources = fields.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            raw_path = source.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                continue
            sha = source.get("sha256")
            record = {
                "note_page": str(path.relative_to(vault)),
                "sha256": str(sha) if sha is not None else None,
            }
            registry.setdefault(raw_path, []).append(record)
    return registry


def classify(path: Path, vault: Path | None = None) -> tuple[str, Path | None]:
    vault = vault or VAULT
    if path.parent == clippings_root(vault):
        return "clipping", clipping_assets_root(vault) / path.stem
    if path.parent == ai_saves_root(vault):
        return "ai-save", ai_save_assets_root(vault) / path.stem
    return "raw", None


def inventory(vault: Path | None = None) -> list[dict[str, object]]:
    vault = vault or VAULT
    raw_files = iter_raw_files(vault)
    registry = note_registry(vault)
    items: list[dict[str, object]] = []
    for path in raw_files:
        kind, asset_dir = classify(path, vault)
        relative = str(path.relative_to(vault))
        digest = sha256(path)
        records = registry.get(relative, [])
        registered_sha256 = records[0]["sha256"] if records else None
        note_page = records[0]["note_page"] if records else None

        if len(records) > 1:
            status = "duplicate"
        elif not records:
            status = "new"
        elif registered_sha256 == digest:
            status = "current"
        else:
            status = "changed"

        item: dict[str, object] = {
            "path": relative,
            "kind": kind,
            "sha256": digest,
            "status": status,
            "registered": bool(records),
            "changed": status == "changed",
            "current_sha256": digest,
            "registered_sha256": registered_sha256,
            "note_page": note_page,
        }
        if len(records) > 1:
            item["note_pages"] = [record["note_page"] for record in records]
        if asset_dir is not None:
            item["asset_dir"] = str(asset_dir.relative_to(vault))
            item["asset_dir_exists"] = asset_dir.exists()
        items.append(item)
    return items


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Inventory local raw sources.")
    cli.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    cli.add_argument("--json", action="store_true", help="Print JSON.")
    return cli


def main() -> int:
    args = parser().parse_args()
    vault = vault_root(args.root)
    raw_files = iter_raw_files(vault)
    notes = clipping_notes(vault)
    saves = ai_saved_pages(vault)
    items = inventory(vault)

    if args.json:
        print(
            json.dumps(
                {"root": str(vault), "vault": str(vault), "items": items},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Raw source inventory")
    print(f"- raw files: {len(raw_files)}")
    print(f"- clipping notes: {len(notes)}")
    print(f"- AI saved pages: {len(saves)}")

    if notes:
        print("\nClippings")
        for note in notes:
            asset_dir = clipping_assets_root(vault) / note.stem
            asset_state = "assets present" if asset_dir.exists() else "no assets"
            item = next(
                item for item in items if item["path"] == str(note.relative_to(vault))
            )
            print(
                f"- {note.relative_to(vault)} "
                f"({asset_state}, {item['status']})"
            )

    if saves:
        print("\nAI saved pages")
        for save in saves:
            asset_dir = ai_save_assets_root(vault) / save.stem
            asset_state = "assets present" if asset_dir.exists() else "no assets"
            item = next(
                item for item in items if item["path"] == str(save.relative_to(vault))
            )
            print(
                f"- {save.relative_to(vault)} "
                f"({asset_state}, {item['status']})"
            )

    other_files = [
        path for path in raw_files if path not in notes and path not in saves
    ]
    if other_files:
        print("\nOther raw files")
        for path in other_files:
            item = next(
                item for item in items if item["path"] == str(path.relative_to(vault))
            )
            print(f"- {path.relative_to(vault)} ({item['status']})")

    if not raw_files:
        print("\nNo local raw source files found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
