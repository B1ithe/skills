#!/usr/bin/env python3
"""Read-only inventory for local raw source material."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from note_common import relative_posix, vault_root
from note_sources import (
    ai_save_assets_root,
    ai_saved_pages,
    clipping_assets_root,
    clipping_notes,
    inventory_sources,
    iter_raw_files,
)

DEFAULT_ROOT = Path(os.environ.get("LLM_NOTE_ROOT", "."))
VAULT = vault_root(DEFAULT_ROOT)


def inventory(vault: Path | None = None) -> list[dict[str, object]]:
    vault = vault or VAULT
    return [item.to_dict() for item in inventory_sources(vault)]


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
    items_by_path = {str(item["path"]): item for item in items}

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
            relative = relative_posix(note, vault)
            item = items_by_path[relative]
            print(
                f"- {relative} "
                f"({asset_state}, {item['status']})"
            )

    if saves:
        print("\nAI saved pages")
        for save in saves:
            asset_dir = ai_save_assets_root(vault) / save.stem
            asset_state = "assets present" if asset_dir.exists() else "no assets"
            relative = relative_posix(save, vault)
            item = items_by_path[relative]
            print(
                f"- {relative} "
                f"({asset_state}, {item['status']})"
            )

    other_files = [
        path for path in raw_files if path not in notes and path not in saves
    ]
    if other_files:
        print("\nOther raw files")
        for path in other_files:
            relative = relative_posix(path, vault)
            item = items_by_path[relative]
            print(f"- {relative} ({item['status']})")

    if not raw_files:
        print("\nNo local raw source files found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
