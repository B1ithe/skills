#!/usr/bin/env python3
"""Find notes without frontmatter and add minimum metadata after approval."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath

from note_common import (
    NoAliasSafeDumper,
    is_maintained_note,
    maintained_notes,
    vault_root,
    yaml,
)

DEFAULT_ROOT = Path(os.environ.get("LLM_NOTE_ROOT", "."))
MANIFEST_VERSION = 1
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
H1_RE = re.compile(r"^ {0,3}#[ \t]+(.+?)\s*$")


class FormatError(Exception):
    """Raised when a requested formatting operation is unsafe."""


def has_frontmatter_marker(text: str) -> bool:
    return bool(text.splitlines()) and text.splitlines()[0] == "---"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def first_h1(text: str) -> str | None:
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is not None:
            continue

        heading_match = H1_RE.match(line)
        if heading_match is None:
            continue
        title = re.sub(r"[ \t]+#+[ \t]*$", "", heading_match.group(1)).strip()
        if title:
            return title
    return None


def candidate(path: Path, vault: Path) -> dict[str, str] | None:
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FormatError(f"{path}: maintained notes must use UTF-8") from exc

    if has_frontmatter_marker(text):
        return None

    return {
        "path": path.relative_to(vault).as_posix(),
        "title": first_h1(text) or path.stem,
        "sha256": sha256_bytes(content),
    }


def scan(root: Path) -> dict[str, object]:
    vault = vault_root(root)
    if not vault.is_dir():
        raise FormatError(f"Vault directory not found: {vault}")

    items: list[dict[str, str]] = []
    for path in maintained_notes(vault):
        item = candidate(path, vault)
        if item is not None:
            items.append(item)
    return {
        "version": MANIFEST_VERSION,
        "root": str(vault),
        "vault": str(vault),
        "items": items,
    }


def safe_note_path(vault: Path, raw_path: str) -> Path:
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise FormatError(f"invalid Vault-relative note path: {raw_path}")

    path = vault.joinpath(*relative.parts)
    if not is_maintained_note(path, vault):
        raise FormatError(f"not a maintained Markdown note: {raw_path}")
    return path


def load_inventory(path: Path, root: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormatError(f"cannot read inventory {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        raise FormatError("unsupported or invalid inventory")
    if data.get("root") != str(root):
        raise FormatError("inventory belongs to a different vault root")

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise FormatError("inventory items must be a list")

    items: dict[str, dict[str, str]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise FormatError("inventory item must be an object")
        note_path = raw_item.get("path")
        title = raw_item.get("title")
        digest = raw_item.get("sha256")
        if not all(isinstance(value, str) for value in (note_path, title, digest)):
            raise FormatError("inventory item fields must be strings")
        if note_path in items:
            raise FormatError(f"duplicate inventory path: {note_path}")
        items[note_path] = {
            "path": note_path,
            "title": title,
            "sha256": digest,
        }
    return items


def frontmatter(title: str, date: dt.date) -> bytes:
    fields = {
        "title": title,
        "created": date,
        "updated": date,
        "tags": [],
        "sources": [],
    }
    yaml_text = yaml.dump(
        fields,
        Dumper=NoAliasSafeDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n\n".encode()


def apply(
    root: Path,
    inventory_path: Path,
    selected: list[str],
    date: dt.date | None = None,
) -> list[str]:
    vault = vault_root(root)
    inventory = load_inventory(inventory_path, vault)
    if not selected:
        raise FormatError("at least one --note path is required")
    if len(selected) != len(set(selected)):
        raise FormatError("duplicate --note paths are not allowed")

    applied_date = date or dt.date.today()
    prepared: list[tuple[Path, bytes, bytes, int, str]] = []
    for raw_path in selected:
        item = inventory.get(raw_path)
        if item is None:
            raise FormatError(f"note was not in the confirmed inventory: {raw_path}")

        path = safe_note_path(vault, raw_path)
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FormatError(f"{raw_path}: maintained notes must use UTF-8") from exc

        if has_frontmatter_marker(text):
            raise FormatError(f"note now has a frontmatter marker: {raw_path}")
        if sha256_bytes(content) != item["sha256"]:
            raise FormatError(f"note changed after scanning: {raw_path}")

        mode = stat.S_IMODE(path.stat().st_mode)
        updated = frontmatter(item["title"], applied_date) + content
        prepared.append((path, content, updated, mode, raw_path))

    temporary: list[tuple[Path, Path, bytes, int, str]] = []
    try:
        for path, original, updated, mode, raw_path in prepared:
            temp = path.with_name(
                f".{path.name}.note-format-{uuid.uuid4().hex}.tmp"
            )
            temp.write_bytes(updated)
            os.chmod(temp, mode)
            temporary.append((temp, path, original, mode, raw_path))

        for _, path, original, _, raw_path in temporary:
            if sha256_bytes(path.read_bytes()) != sha256_bytes(original):
                raise FormatError(f"note changed before writing: {raw_path}")

        replaced: list[tuple[Path, bytes, int]] = []
        try:
            for temp, path, original, mode, _ in temporary:
                os.replace(temp, path)
                replaced.append((path, original, mode))
        except OSError:
            for path, original, mode in reversed(replaced):
                path.write_bytes(original)
                os.chmod(path, mode)
            raise
    finally:
        for temp, _, _, _, _ in temporary:
            temp.unlink(missing_ok=True)

    return selected


def print_scan(data: dict[str, object]) -> None:
    items = data["items"]
    assert isinstance(items, list)
    if not items:
        print("No maintained notes without frontmatter.")
        return

    print("Maintained notes without frontmatter:")
    for index, item in enumerate(items, start=1):
        assert isinstance(item, dict)
        print(f"{index}. {item['path']} (title: {item['title']})")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="Find and format maintained notes without frontmatter."
    )
    subparsers = cli.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="List eligible notes.")
    scan_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    scan_parser.add_argument("--json", action="store_true", help="Print JSON.")

    apply_parser = subparsers.add_parser(
        "apply",
        help="Add frontmatter to explicitly selected inventory items.",
    )
    apply_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    apply_parser.add_argument("--inventory", type=Path, required=True)
    apply_parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Vault-relative note path; repeat for multiple notes.",
    )
    apply_parser.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        help=argparse.SUPPRESS,
    )
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "scan":
            data = scan(args.root)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print_scan(data)
            return 0

        paths = apply(args.root, args.inventory, args.note, args.date)
        print(f"Added frontmatter to {len(paths)} notes:")
        for path in paths:
            print(f"- {path}")
        return 0
    except (FormatError, OSError) as exc:
        print(f"note-format failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
