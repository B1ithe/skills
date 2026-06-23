from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

from note_common import IGNORED_LOCAL_SCHEMES, WIKILINK_RE, replace_outside_fences


@dataclass(frozen=True)
class MarkdownTarget:
    raw: str
    path: str
    prefix: str
    suffix: str
    fragment: str
    angled: bool
    is_image: bool

    def with_path(self, encoded_path: str) -> str:
        target = f"{encoded_path}{self.fragment}"
        if self.angled:
            target = f"<{target}>"
        return f"{self.prefix}{target}{self.suffix}"


@dataclass(frozen=True)
class WikiTarget:
    target: str
    heading: str
    alias: str

    @property
    def normalized(self) -> str:
        return self.target.strip().removesuffix(".md").removeprefix("./")


def _closing_bracket(line: str, start: int) -> int | None:
    escaped = False
    for index in range(start, len(line)):
        char = line[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "]":
            return index
    return None


def _closing_paren(line: str, start: int) -> int | None:
    depth = 1
    escaped = False
    angled = False
    for index in range(start, len(line)):
        char = line[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "<" and not angled:
            angled = True
            continue
        if char == ">" and angled:
            angled = False
            continue
        if angled:
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _raw_markdown_links(line: str) -> list[tuple[int, int, bool]]:
    links: list[tuple[int, int, bool]] = []
    index = 0
    while index < len(line):
        is_image = line.startswith("![", index)
        if is_image:
            label_start = index + 2
        elif line[index] == "[" and (index == 0 or line[index - 1] != "!"):
            label_start = index + 1
        else:
            index += 1
            continue

        label_end = _closing_bracket(line, label_start)
        if label_end is None or label_end + 1 >= len(line) or line[label_end + 1] != "(":
            index += 1
            continue

        target_start = label_end + 2
        target_end = _closing_paren(line, target_start)
        if target_end is None:
            index += 1
            continue

        links.append((target_start, target_end, is_image))
        index = target_end + 1
    return links


def _split_destination(raw: str, is_image: bool) -> MarkdownTarget | None:
    prefix = raw[: len(raw) - len(raw.lstrip())]
    rest = raw[len(prefix) :]
    if not rest:
        return None

    angled = rest.startswith("<") and ">" in rest
    if angled:
        end = rest.index(">")
        token = rest[1:end]
        suffix = rest[end + 1 :]
    else:
        token = rest.split(maxsplit=1)[0]
        suffix = rest[len(token) :]

    if not token:
        return None

    path_token, separator, fragment = token.partition("#")
    target = unquote(path_token)
    fragment_text = f"#{fragment}" if separator else ""
    return MarkdownTarget(
        raw=raw,
        path=target,
        prefix=prefix,
        suffix=suffix,
        fragment=fragment_text,
        angled=angled,
        is_image=is_image,
    )


def is_local_markdown_target(target: MarkdownTarget) -> bool:
    probe = target.path.lower()
    return bool(probe) and not probe.startswith(IGNORED_LOCAL_SCHEMES)


def markdown_targets_in_line(line: str) -> list[MarkdownTarget]:
    targets: list[MarkdownTarget] = []
    for start, end, is_image in _raw_markdown_links(line):
        target = _split_destination(line[start:end], is_image)
        if target is not None and is_local_markdown_target(target):
            targets.append(target)
    return targets


def local_markdown_targets(text: str) -> list[MarkdownTarget]:
    targets: list[MarkdownTarget] = []

    def collect(line: str) -> str:
        targets.extend(markdown_targets_in_line(line))
        return line

    replace_outside_fences(text, collect)
    return targets


def replace_local_markdown_targets(text: str, replacer) -> str:
    def replace_line(line: str) -> str:
        pieces: list[str] = []
        cursor = 0
        for start, end, is_image in _raw_markdown_links(line):
            target = _split_destination(line[start:end], is_image)
            if target is None or not is_local_markdown_target(target):
                continue
            replacement = replacer(target)
            if replacement is None:
                continue
            pieces.append(line[cursor:start])
            pieces.append(replacement)
            cursor = end
        if not pieces:
            return line
        pieces.append(line[cursor:])
        return "".join(pieces)

    return replace_outside_fences(text, replace_line)


def wikilink_targets(text: str) -> list[WikiTarget]:
    targets: list[WikiTarget] = []

    def collect(line: str) -> str:
        for match in WIKILINK_RE.finditer(line):
            targets.append(
                WikiTarget(
                    target=match.group(1),
                    heading=match.group(2) or "",
                    alias=match.group(3) or "",
                )
            )
        return line

    replace_outside_fences(text, collect)
    return targets


def replace_wikilinks(text: str, replacer) -> str:
    def replace_line(line: str) -> str:
        def replace_match(match) -> str:
            target = WikiTarget(
                target=match.group(1),
                heading=match.group(2) or "",
                alias=match.group(3) or "",
            )
            replacement = replacer(target)
            if replacement is None:
                return match.group(0)
            return f"[[{replacement}{target.heading}{target.alias}]]"

        return WIKILINK_RE.sub(replace_match, line)

    return replace_outside_fences(text, replace_line)


def encode_markdown_path(path: str) -> str:
    return quote(path, safe="./")
