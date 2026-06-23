from __future__ import annotations

import datetime as dt
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
    if exc.name == "yaml":
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        raise SystemExit(
            "PyYAML is required. Run: "
            f"python -m pip install -r {requirements}"
        ) from exc
    raise


class NoAliasSafeDumper(yaml.SafeDumper):
    """Emit repeated scalar values directly instead of YAML aliases."""

    def ignore_aliases(self, data: object) -> bool:
        return True


REQUIRED_FIELDS = {"title", "created", "updated", "tags", "sources"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
WIKILINK_RE = re.compile(
    r"(?<!!)\[\[([^\]|#]+)(#[^\]|]*)?(\|[^\]]*)?\]\]"
)
UNSAFE_FILENAME_CHARS = set('<>:"/\\|?*')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
IGNORED_LOCAL_SCHEMES = (
    "http://",
    "https://",
    "mailto:",
    "javascript:",
    "data:",
    "#",
    "$",
)
IGNORED_VAULT_DIRS = {".git", ".obsidian"}


def vault_root(root: Path) -> Path:
    return root.expanduser().resolve()


def is_maintained_note(path: Path, vault: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".md":
        return False

    try:
        relative = path.relative_to(vault)
        path.resolve().relative_to(vault.resolve())
    except ValueError:
        return False

    if relative.parts and relative.parts[0] == "RAW":
        return False
    return ".obsidian" not in relative.parts and "assets" not in relative.parts


def is_ignored_vault_path(path: Path, vault: Path) -> bool:
    return any(part in IGNORED_VAULT_DIRS for part in path.relative_to(vault).parts)


def maintained_notes(vault: Path) -> list[Path]:
    if not vault.exists():
        return []
    return sorted(
        path for path in vault.rglob("*.md") if is_maintained_note(path, vault)
    )


def parse_frontmatter(text: str) -> tuple[dict[str, object], list[str]]:
    if not text.startswith("---\n"):
        return {}, ["missing YAML frontmatter"]

    end = text.find("\n---", 4)
    if end == -1:
        return {}, ["unterminated YAML frontmatter"]

    try:
        data = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        return {}, [f"invalid YAML frontmatter: {exc}"]

    if not isinstance(data, dict):
        return {}, ["YAML frontmatter must be a mapping"]

    return data, []


def split_frontmatter(text: str) -> tuple[dict[str, object], str, list[str]]:
    fields, errors = parse_frontmatter(text)
    if errors:
        return {}, text, errors
    end = text.find("\n---", 4)
    body_start = end + len("\n---")
    if text[body_start : body_start + 1] == "\n":
        body_start += 1
    return fields, text[body_start:], []


def dump_frontmatter(fields: dict[str, object]) -> str:
    yaml_text = yaml.dump(
        fields,
        Dumper=NoAliasSafeDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n"


def valid_date(value: object) -> bool:
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def prose_text(text: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                output.append("\n")
            else:
                output.append(line)
            continue

        if re.match(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", line):
            fence = None
        output.append("\n")
    return "".join(output)


def replace_outside_fences(text: str, replace_line) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                output.append(line)
            else:
                output.append(replace_line(line))
            continue

        output.append(line)
        if re.match(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", line):
            fence = None
    return "".join(output)


def image_target(raw_target: str) -> str:
    value = raw_target.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def local_attachment_targets(text: str) -> set[str]:
    prose = prose_text(text)
    targets = set(MARKDOWN_IMAGE_RE.findall(prose))
    targets.update(MARKDOWN_LINK_RE.findall(prose))
    return targets


def is_local_target(target: str) -> bool:
    return not target.startswith(IGNORED_LOCAL_SCHEMES)


def normalize_link_target(target: str) -> str:
    return unquote(image_target(target).split("#", 1)[0])


def path_part_errors(name: str) -> list[str]:
    errors: list[str] = []
    if name in {"", ".", ".."}:
        errors.append("filename must not be empty, . or ..")
    bad = sorted(char for char in set(name) if char in UNSAFE_FILENAME_CHARS)
    if bad:
        errors.append(f"contains reserved character(s): {' '.join(bad)}")
    if any(ord(char) < 32 for char in name):
        errors.append("contains control character(s)")
    if name.endswith((" ", ".")):
        errors.append("must not end with a space or dot")
    stem = name.rsplit(".", 1)[0].upper()
    if stem in RESERVED_WINDOWS_NAMES:
        errors.append("uses a Windows reserved device name")
    return errors


def is_safe_path_part(name: str) -> bool:
    return not path_part_errors(name)


def safe_path_part(name: str, is_file: bool = False) -> str:
    suffix = ""
    stem = name
    if is_file:
        suffix = PurePosixPath(name).suffix
        if suffix:
            stem = name[: -len(suffix)]

    cleaned = "".join(
        " " if char in UNSAFE_FILENAME_CHARS or ord(char) < 32 else char
        for char in stem
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "untitled-note"
    if cleaned.upper() in RESERVED_WINDOWS_NAMES:
        cleaned = f"{cleaned}-note"
    return f"{cleaned}{suffix}"


def iter_vault_paths(vault: Path) -> list[Path]:
    if not vault.exists():
        return []
    return sorted(
        (path for path in vault.rglob("*") if not is_ignored_vault_path(path, vault)),
        key=lambda path: path.relative_to(vault).parts,
    )


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
