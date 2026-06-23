#!/usr/bin/env python3
"""Plan and apply cross-platform filename repairs for a note vault."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath

from note_markdown import (
    encode_markdown_path,
    replace_local_markdown_targets,
    replace_wikilinks,
)
from note_sources import update_frontmatter_sources
from note_common import (
    dump_frontmatter,
    is_ignored_vault_path,
    maintained_notes,
    path_part_errors,
    relative_posix,
    replace_outside_fences,
    safe_path_part,
    split_frontmatter,
    vault_root,
)

DEFAULT_ROOT = Path(os.environ.get("LLM_NOTE_ROOT", "."))
MANIFEST_VERSION = 1


class RenameError(Exception):
    """Raised when a rename plan cannot be safely applied."""


def append_counter(name: str, counter: int, is_file: bool) -> str:
    suffix = PurePosixPath(name).suffix if is_file else ""
    stem = name[: -len(suffix)] if suffix else name
    return f"{stem}-{counter}{suffix}"


def allocate_child_names(children: list[Path]) -> tuple[dict[str, str], list[str]]:
    allocated: dict[str, str] = {}
    conflicts: list[str] = []
    used: set[str] = set()
    sortable = []
    for child in children:
        desired = (
            safe_path_part(child.name, child.is_file())
            if path_part_errors(child.name)
            else child.name
        )
        sortable.append((desired != child.name, child.name.casefold(), child, desired))

    for _, _, child, desired in sorted(sortable):
        candidate = desired
        counter = 2
        while candidate in used:
            candidate = append_counter(desired, counter, child.is_file())
            counter += 1
        allocated[child.name] = candidate
        used.add(candidate)

    by_casefold: dict[str, list[str]] = {}
    for name in allocated.values():
        by_casefold.setdefault(name.casefold(), []).append(name)
    for names in by_casefold.values():
        if len(names) > 1:
            conflicts.append(
                "case-insensitive filename conflict after planning: "
                + ", ".join(sorted(names))
            )
    return allocated, conflicts


def build_mapping(
    vault: Path,
    directory: Path,
    final_directory: PurePosixPath,
    mapping: dict[str, str],
    renames: list[dict[str, object]],
    conflicts: list[str],
) -> None:
    try:
        children = [
            child
            for child in directory.iterdir()
            if not is_ignored_vault_path(child, vault)
        ]
    except OSError as exc:
        conflicts.append(f"cannot read {relative_posix(directory, vault)}: {exc}")
        return

    allocated, allocation_conflicts = allocate_child_names(children)
    conflicts.extend(
        f"{relative_posix(directory, vault)}: {conflict}"
        if directory != vault
        else f".: {conflict}"
        for conflict in allocation_conflicts
    )

    for child in sorted(children, key=lambda path: path.name.casefold()):
        final_name = allocated[child.name]
        old_rel = PurePosixPath(child.relative_to(vault).as_posix())
        new_rel = final_directory / final_name
        if old_rel.as_posix() != new_rel.as_posix():
            mapping[old_rel.as_posix()] = new_rel.as_posix()
        if child.name != final_name:
            reasons = path_part_errors(child.name)
            renames.append(
                {
                    "path": old_rel.as_posix(),
                    "new_path": new_rel.as_posix(),
                    "kind": "directory" if child.is_dir() else "file",
                    "reason": "; ".join(reasons) if reasons else "deduplicated",
                }
            )
        if child.is_dir():
            build_mapping(vault, child, new_rel, mapping, renames, conflicts)


def include_descendant_updates(vault: Path, mapping: dict[str, str]) -> None:
    for path in sorted(vault.rglob("*"), key=lambda item: len(item.parts)):
        if is_ignored_vault_path(path, vault):
            continue
        old_rel = path.relative_to(vault).as_posix()
        if old_rel in mapping:
            continue
        for old_prefix, new_prefix in sorted(
            mapping.items(),
            key=lambda item: len(PurePosixPath(item[0]).parts),
            reverse=True,
        ):
            if old_rel.startswith(f"{old_prefix}/"):
                mapping[old_rel] = f"{new_prefix}{old_rel[len(old_prefix):]}"
                break


def raw_markdown_warnings(mapping: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    for old, new in sorted(mapping.items()):
        if old.startswith("RAW/") and old.endswith(".md"):
            warnings.append(
                f"{old} -> {new}: RAW Markdown content is not edited; "
                "relative links inside the source may need manual review."
            )
    return warnings


def plan(root: Path) -> dict[str, object]:
    vault = vault_root(root)
    mapping: dict[str, str] = {}
    renames: list[dict[str, object]] = []
    conflicts: list[str] = []
    build_mapping(vault, vault, PurePosixPath("."), mapping, renames, conflicts)

    normalized_mapping = {
        old: new[2:] if new.startswith("./") else new
        for old, new in mapping.items()
    }
    include_descendant_updates(vault, normalized_mapping)
    return {
        "version": MANIFEST_VERSION,
        "root": str(vault),
        "renames": renames,
        "path_updates": dict(sorted(normalized_mapping.items())),
        "conflicts": conflicts,
        "warnings": raw_markdown_warnings(normalized_mapping),
    }


def load_plan(path: Path, root: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RenameError(f"cannot read plan {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        raise RenameError("unsupported or invalid rename plan")
    if data.get("root") != str(root):
        raise RenameError("rename plan belongs to a different vault root")
    conflicts = data.get("conflicts")
    if conflicts:
        raise RenameError("rename plan has conflicts; resolve them before apply")
    return data


def remap_completed(path: str, completed: list[tuple[str, str]]) -> str:
    for old, new in sorted(
        completed,
        key=lambda item: len(PurePosixPath(item[0]).parts),
        reverse=True,
    ):
        if path == old:
            return new
        if path.startswith(f"{old}/"):
            return f"{new}{path[len(old):]}"
    return path


def apply_renames(vault: Path, renames: list[dict[str, object]]) -> None:
    completed: list[tuple[str, str]] = []
    for operation in sorted(
        renames,
        key=lambda item: len(PurePosixPath(str(item["path"])).parts),
    ):
        old = str(operation["path"])
        new = str(operation["new_path"])
        current = remap_completed(old, completed)
        source = vault.joinpath(*PurePosixPath(current).parts)
        target = vault.joinpath(*PurePosixPath(new).parts)
        if not source.exists():
            raise RenameError(f"planned source no longer exists: {current}")
        if target.exists():
            raise RenameError(f"planned target already exists: {new}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        completed.append((old, new))


def note_link_maps(path_updates: dict[str, str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    target_updates: dict[str, str] = {}
    asset_updates: dict[str, tuple[str, str]] = {}
    stem_counts: dict[str, int] = {}
    for old in path_updates:
        old_path = PurePosixPath(old)
        if old_path.suffix == ".md" and old_path.parts[0] != "RAW":
            stem_counts[old_path.stem] = stem_counts.get(old_path.stem, 0) + 1

    for old, new in path_updates.items():
        old_path = PurePosixPath(old)
        new_path = PurePosixPath(new)
        if old_path.suffix != ".md" or old_path.parts[0] == "RAW":
            continue
        old_target = old_path.with_suffix("").as_posix()
        new_target = new_path.with_suffix("").as_posix()
        target_updates[old_target] = new_target
        if stem_counts.get(old_path.stem) == 1:
            target_updates[old_path.stem] = new_path.stem
        if old_path.stem != new_path.stem:
            asset_updates[new] = (old_path.stem, new_path.stem)
    return target_updates, asset_updates


def relative_markdown_target(vault: Path, note_path: Path, vault_relative: str) -> str:
    absolute = vault.joinpath(*PurePosixPath(vault_relative).parts)
    relative = Path(os.path.relpath(absolute, note_path.parent)).as_posix()
    if not relative.startswith("."):
        relative = f"./{relative}"
    return encode_markdown_path(relative)


def remap_markdown_target(
    target,
    vault: Path,
    note_path: Path,
    path_updates: dict[str, str],
) -> str | None:
    try:
        current = (note_path.parent / target.path).resolve()
        current_relative = current.relative_to(vault).as_posix()
    except ValueError:
        return None

    updated_relative = path_updates.get(current_relative)
    if updated_relative is None:
        return None

    updated = relative_markdown_target(vault, note_path, updated_relative)
    return target.with_path(updated)


def update_asset_links(line: str, old_stem: str, new_stem: str) -> str:
    return line.replace(
        f"./assets/{old_stem}/",
        f"./assets/{new_stem}/",
    ).replace(
        f"assets/{old_stem}/",
        f"assets/{new_stem}/",
    )


def preflight_renames(vault: Path, renames: list[dict[str, object]]) -> None:
    completed: list[tuple[str, str]] = []
    targets: set[str] = set()
    for operation in sorted(
        renames,
        key=lambda item: len(PurePosixPath(str(item["path"])).parts),
    ):
        old = str(operation["path"])
        new = str(operation["new_path"])
        current = remap_completed(old, completed)
        source = vault.joinpath(*PurePosixPath(current).parts)
        target = vault.joinpath(*PurePosixPath(new).parts)
        if not source.exists():
            raise RenameError(f"planned source no longer exists: {current}")
        if new in targets or target.exists():
            raise RenameError(f"planned target already exists: {new}")
        targets.add(new)
        completed.append((old, new))


def prepare_note_updates(vault: Path, path_updates: dict[str, str]) -> list[tuple[Path, str]]:
    target_updates, asset_updates = note_link_maps(path_updates)
    updates: list[tuple[Path, str]] = []
    for path in maintained_notes(vault):
        rel = path.relative_to(vault).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RenameError(f"{rel}: maintained notes must use UTF-8") from exc
        fields, body, errors = split_frontmatter(text)
        original_frontmatter = ""
        frontmatter_changed = False
        if not errors:
            original_frontmatter = text[: len(text) - len(body)]
            frontmatter_changed = update_frontmatter_sources(fields, path_updates)
        else:
            body = text

        new_body = replace_wikilinks(
            body,
            lambda target: target_updates.get(target.normalized),
        )
        new_body = replace_local_markdown_targets(
            new_body,
            lambda target: remap_markdown_target(target, vault, path, path_updates),
        )

        asset_update = asset_updates.get(rel)
        if asset_update is not None:
            new_body = replace_outside_fences(
                new_body,
                lambda line: update_asset_links(line, *asset_update),
            )
        if errors:
            new_text = new_body
        elif frontmatter_changed:
            new_text = dump_frontmatter(fields) + new_body
        else:
            new_text = original_frontmatter + new_body

        if frontmatter_changed or new_body != body:
            updates.append((path, new_text))
    return updates


def write_note_updates(updates: list[tuple[Path, str]], vault: Path) -> list[str]:
    changed: list[str] = []
    for path, text in updates:
        path.write_text(text, encoding="utf-8")
        changed.append(relative_posix(path, vault))
    return changed


def apply(root: Path, plan_path: Path) -> dict[str, object]:
    vault = vault_root(root)
    data = load_plan(plan_path, vault)
    raw_renames = data.get("renames")
    raw_updates = data.get("path_updates")
    if not isinstance(raw_renames, list) or not isinstance(raw_updates, dict):
        raise RenameError("rename plan is missing renames or path_updates")

    renames = [item for item in raw_renames if isinstance(item, dict)]
    path_updates = {
        str(old): str(new)
        for old, new in raw_updates.items()
        if isinstance(old, str) and isinstance(new, str)
    }
    preflight_renames(vault, renames)
    note_updates = prepare_note_updates(vault, path_updates)
    apply_renames(vault, renames)
    changed_notes = write_note_updates(note_updates, vault)
    return {
        "renamed": len(renames),
        "updated_notes": changed_notes,
    }


def print_plan(data: dict[str, object]) -> None:
    renames = data.get("renames")
    conflicts = data.get("conflicts")
    warnings = data.get("warnings")
    assert isinstance(renames, list)
    assert isinstance(conflicts, list)
    assert isinstance(warnings, list)
    if not renames:
        print("No unsafe filenames found.")
    else:
        print("Planned filename repairs:")
        for item in renames:
            assert isinstance(item, dict)
            print(f"- {item['path']} -> {item['new_path']} ({item['reason']})")
    if conflicts:
        print("\nConflicts:")
        for conflict in conflicts:
            print(f"- {conflict}")
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"- {warning}")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Repair unsafe note vault filenames.")
    subparsers = cli.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Plan filename repairs.")
    plan_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    plan_parser.add_argument("--json", action="store_true", help="Print JSON.")

    apply_parser = subparsers.add_parser("apply", help="Apply a confirmed plan.")
    apply_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    apply_parser.add_argument("--plan", type=Path, required=True)
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "plan":
            data = plan(args.root)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print_plan(data)
            return 0

        result = apply(args.root, args.plan)
        print(f"Renamed {result['renamed']} filesystem entries.")
        updated_notes = result["updated_notes"]
        assert isinstance(updated_notes, list)
        if updated_notes:
            print("Updated notes:")
            for path in updated_notes:
                print(f"- {path}")
        return 0
    except (RenameError, OSError) as exc:
        print(f"note-rename failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
