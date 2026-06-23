#!/usr/bin/env python3
"""Health checks for a Markdown/Obsidian note vault."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PurePosixPath

from note_markdown import local_markdown_targets, wikilink_targets
from note_sources import source_health_errors
from note_common import (
    REQUIRED_FIELDS,
    SHA256_RE,
    is_ignored_vault_path,
    iter_vault_paths,
    maintained_notes,
    parse_frontmatter,
    path_part_errors,
    relative_posix,
    valid_date,
    vault_root,
)

DEFAULT_ROOT = Path(os.environ.get("LLM_NOTE_ROOT", "."))
VAULT = vault_root(DEFAULT_ROOT)


def note_files(vault: Path | None = None) -> list[Path]:
    return maintained_notes(vault or VAULT)


def validate_source(source: object, index: int) -> list[str]:
    prefix = f"sources[{index}]"
    if not isinstance(source, dict):
        return [f"{prefix} must be a mapping"]

    errors: list[str] = []
    source_path = source.get("path")
    if not isinstance(source_path, str) or not source_path:
        errors.append(f"{prefix}.path must be a non-empty string")
    else:
        normalized = PurePosixPath(source_path)
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or not normalized.parts
            or normalized.parts[0] != "RAW"
        ):
            errors.append(f"{prefix}.path must be a Vault-relative RAW/ path")

    sha256 = source.get("sha256")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        errors.append(f"{prefix}.sha256 must be a lowercase SHA-256 digest")

    url = source.get("url")
    if url is not None and not isinstance(url, str):
        errors.append(f"{prefix}.url must be a string")

    return errors


def check_frontmatter(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    fields, errors = parse_frontmatter(text)
    if errors == ["missing YAML frontmatter"]:
        return [], ["needs_format: missing YAML frontmatter"]
    if not fields:
        return errors, []

    advisories: list[str] = []

    missing = sorted(REQUIRED_FIELDS - set(fields))
    if missing:
        advisories.append(
            "needs_update: missing frontmatter fields: "
            + ", ".join(missing)
        )

    if "title" in fields and not isinstance(fields["title"], str):
        errors.append("title must be a string")

    for field in ("created", "updated"):
        if field in fields and not valid_date(fields[field]):
            errors.append(f"{field} must use YYYY-MM-DD")

    tags = fields.get("tags")
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
    ):
        errors.append("tags must be a list of strings")

    sources = fields.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            errors.append("sources must be a list")
        else:
            for index, source in enumerate(sources):
                errors.extend(validate_source(source, index))

    return errors, advisories


def note_targets(files: list[Path], vault: Path | None = None) -> set[str]:
    vault = vault or VAULT
    targets: set[str] = set()
    for path in files:
        relative = path.relative_to(vault).with_suffix("").as_posix()
        targets.add(relative)
        targets.add(path.stem)

        fields, parse_errors = parse_frontmatter(path.read_text(encoding="utf-8"))
        title = fields.get("title") if not parse_errors else None
        if isinstance(title, str):
            targets.add(title)
    return targets


def check_links(files: list[Path], vault: Path | None = None) -> list[str]:
    vault = vault or VAULT
    errors: list[str] = []
    targets = note_targets(files, vault)
    for path in files:
        text = path.read_text(encoding="utf-8")
        for link in sorted(wikilink_targets(text), key=lambda item: item.target):
            if link.normalized not in targets:
                relative = path.relative_to(vault)
                errors.append(f"{relative}: broken internal link [[{link.target}]]")
    return errors


def check_duplicate_filenames(
    files: list[Path],
    vault: Path | None = None,
) -> list[str]:
    vault = vault or VAULT
    by_stem: dict[str, list[Path]] = {}
    for path in files:
        by_stem.setdefault(path.stem, []).append(path)

    errors: list[str] = []
    for stem, paths in sorted(by_stem.items()):
        if len(paths) > 1:
            relative_paths = ", ".join(relative_posix(path, vault) for path in paths)
            errors.append(f"duplicate note filename {stem}.md: {relative_paths}")
    return errors


def check_attachments(files: list[Path], vault: Path | None = None) -> list[str]:
    vault = vault or VAULT
    errors: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        expected_root = (path.parent / "assets" / path.stem).resolve()
        for target in sorted(local_markdown_targets(text), key=lambda item: item.path):
            candidate = (path.parent / target.path).resolve()
            relative = path.relative_to(vault)
            try:
                candidate.relative_to(expected_root)
            except ValueError:
                errors.append(
                    f"{relative}: attachment must be under "
                    f"./assets/{path.stem}/: {target.path}"
                )
                continue
            if not candidate.is_file():
                errors.append(f"{relative}: missing attachment {target.path}")
    return errors


def check_filename_safety(vault: Path) -> list[str]:
    errors: list[str] = []
    for path in iter_vault_paths(vault):
        reasons = path_part_errors(path.name)
        if reasons:
            errors.append(
                f"{relative_posix(path, vault)}: unsafe filename "
                f"{path.name!r}: {'; '.join(reasons)}"
            )
    errors.extend(check_casefold_conflicts(vault))
    return errors


def check_casefold_conflicts(vault: Path) -> list[str]:
    errors: list[str] = []
    directories = [vault]
    directories.extend(path for path in iter_vault_paths(vault) if path.is_dir())
    for directory in directories:
        by_key: dict[str, list[str]] = {}
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if is_ignored_vault_path(child, vault):
                continue
            by_key.setdefault(child.name.casefold(), []).append(child.name)
        for names in sorted(by_key.values()):
            if len(names) > 1:
                location = "." if directory == vault else relative_posix(directory, vault)
                errors.append(
                    f"{location}: filenames differ only by case: "
                    f"{', '.join(sorted(names))}"
                )
    return errors


def collect_report(vault: Path) -> tuple[list[str], list[str]]:
    files = note_files(vault)
    errors: list[str] = []
    advisories: list[str] = []

    if not files:
        errors.append("vault: no maintained Markdown notes found")

    for path in files:
        relative = path.relative_to(vault)
        frontmatter_errors, frontmatter_advisories = check_frontmatter(path)
        for error in frontmatter_errors:
            errors.append(f"{relative}: {error}")
        for advisory in frontmatter_advisories:
            advisories.append(f"{relative}: {advisory}")

    errors.extend(source_health_errors(vault))
    errors.extend(check_duplicate_filenames(files, vault))
    errors.extend(check_links(files, vault))
    errors.extend(check_attachments(files, vault))
    errors.extend(check_filename_safety(vault))
    return errors, advisories


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Check note vault health.")
    cli.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return cli


def main() -> int:
    args = parser().parse_args()
    vault = vault_root(args.root)
    errors, advisories = collect_report(vault)

    if errors:
        print("Note health check failed:")
        for error in errors:
            print(f"- {error}")
        if advisories:
            print("\nUpdate/format candidates (not health blockers):")
            for advisory in advisories:
                print(f"- {advisory}")
        if any("unsafe filename" in error for error in errors):
            rename_script = Path(__file__).with_name("note_rename.py")
            print(
                "\nUnsafe filenames can be planned with:\n"
                f"  python {rename_script} plan --root {vault} --json"
            )
        return 1

    if advisories:
        print("Note health check passed with update/format candidates:")
        for advisory in advisories:
            print(f"- {advisory}")
        return 0

    print(f"Note health check passed: {len(note_files(vault))} Markdown notes checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
