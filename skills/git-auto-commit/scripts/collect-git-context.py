#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


CONVENTIONAL_SUBJECT = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: "
)
CONVENTIONAL_SCOPE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)\(([^)]+)\)!?: "
)
SENSITIVE_PATTERNS = [
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)\.npmrc$", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519)(\.pub)?$", re.IGNORECASE),
    re.compile(r"\.(pem|p12|pfx|key)$", re.IGNORECASE),
    re.compile(r"(credential|credentials|secret|secrets|private[_-]?key|api[_-]?key|token)", re.IGNORECASE),
]
REVIEW_PATTERNS = [
    re.compile(r"(^|/)(dist|build|coverage|target|out|\.next|node_modules)(/|$)", re.IGNORECASE),
    re.compile(r"\.(class|pyc|o|so|dll|exe|jar|war)$", re.IGNORECASE),
    re.compile(r"\.(min\.js|min\.css|map)$", re.IGNORECASE),
]
STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        command = "git " + " ".join(args)
        error = result.stderr.decode("utf-8", "replace").strip() or "unknown git error"
        raise RuntimeError(f"{command} failed: {error}")
    return result


def decode(value: bytes) -> str:
    return value.decode("utf-8", "replace").strip()


def parse_status(raw: bytes) -> list[dict[str, str | None]]:
    entries = raw.split(b"\0")
    parsed: list[dict[str, str | None]] = []
    index = 0

    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue

        status = entry[:2].decode("ascii", "replace")
        path = entry[3:].decode("utf-8", "replace")
        original_path = None

        if "R" in status or "C" in status:
            if index < len(entries) and entries[index]:
                original_path = path
                path = entries[index].decode("utf-8", "replace")
                index += 1

        parsed.append(
            {
                "status": status,
                "path": path,
                "original_path": original_path,
            }
        )

    return parsed


def summarize_entries(entries: list[dict[str, str | None]]) -> tuple[list[str], Counter[str]]:
    lines: list[str] = []
    counts: Counter[str] = Counter()

    for entry in entries:
        status = entry["status"] or "  "
        path = entry["path"] or ""
        original_path = entry["original_path"]

        if status == "??":
            counts["untracked"] += 1
            lines.append(f"- untracked: {path}")
            continue
        if status == "!!":
            counts["ignored"] += 1
            lines.append(f"- ignored: {path}")
            continue

        staged_state = status[0]
        unstaged_state = status[1]

        if staged_state not in {" ", "?", "!"}:
            counts["staged"] += 1
            label = STATUS_LABELS.get(staged_state, staged_state)
            if original_path:
                lines.append(f"- staged {label}: {original_path} -> {path}")
            else:
                lines.append(f"- staged {label}: {path}")

        if unstaged_state not in {" ", "?", "!"}:
            counts["unstaged"] += 1
            label = STATUS_LABELS.get(unstaged_state, unstaged_state)
            if original_path and unstaged_state in {"R", "C"}:
                lines.append(f"- unstaged {label}: {original_path} -> {path}")
            else:
                lines.append(f"- unstaged {label}: {path}")

    return lines, counts


def collect_paths(entries: list[dict[str, str | None]]) -> list[str]:
    paths: list[str] = []
    for entry in entries:
        original_path = entry["original_path"]
        if original_path:
            paths.append(original_path)
        if entry["path"]:
            paths.append(entry["path"] or "")
    return sorted({path for path in paths if path})


def detect_flagged_paths(paths: list[str], patterns: list[re.Pattern[str]]) -> list[str]:
    flagged: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if any(pattern.search(normalized) for pattern in patterns):
            flagged.append(path)
    return flagged


def top_areas(paths: list[str]) -> list[str]:
    areas = Counter()
    for path in paths:
        parts = Path(path).parts
        if len(parts) <= 1:
            areas["(repo root)"] += 1
        else:
            areas[parts[0]] += 1
    return [f"{name} ({count})" for name, count in areas.most_common(5)]


def collect_recent_commits(repo: Path, limit: int) -> tuple[list[tuple[str, str, str]], dict[str, object]]:
    raw = git(repo, "log", f"-n{limit}", "--format=%h%x00%s%x00%b%x1e").stdout
    records: list[tuple[str, str, str]] = []
    conventional_count = 0
    body_count = 0
    types = Counter()
    scopes = Counter()

    for chunk in raw.split(b"\x1e"):
        chunk = chunk.strip(b"\n")
        if not chunk:
            continue
        pieces = chunk.split(b"\x00", maxsplit=2)
        if len(pieces) < 3:
            continue
        short_hash = decode(pieces[0])
        subject = decode(pieces[1])
        body = decode(pieces[2])
        records.append((short_hash, subject, body))

        match = CONVENTIONAL_SUBJECT.match(subject)
        if match:
            conventional_count += 1
            types[match.group(1)] += 1
            scope_match = CONVENTIONAL_SCOPE.match(subject)
            if scope_match:
                scopes[scope_match.group(2)] += 1

        if body:
            body_count += 1

    total = len(records)
    style = "conventional" if total and conventional_count / total >= 0.6 else "free-form"

    return records, {
        "style": style,
        "total": total,
        "conventional_count": conventional_count,
        "body_count": body_count,
        "types": types.most_common(3),
        "scopes": scopes.most_common(3),
    }


def format_block(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "(none)"
    return f"## {title}\n{body}\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect Git status, diff summaries, and commit-style hints for drafting a detailed commit."
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository path (defaults to current directory)")
    parser.add_argument("--recent", type=int, default=10, help="Number of recent commits to inspect")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()

    try:
        inside = decode(git(repo, "rev-parse", "--is-inside-work-tree").stdout)
        if inside != "true":
            print("Not inside a Git work tree.", file=sys.stderr)
            return 1

        repo_root = decode(git(repo, "rev-parse", "--show-toplevel").stdout)
        branch = decode(git(repo, "branch", "--show-current").stdout) or "(detached HEAD)"
        status_entries = parse_status(git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout)
        changed_paths = collect_paths(status_entries)
        changed_lines, counts = summarize_entries(status_entries)
        sensitive_paths = detect_flagged_paths(changed_paths, SENSITIVE_PATTERNS)
        review_paths = [
            path for path in detect_flagged_paths(changed_paths, REVIEW_PATTERNS) if path not in sensitive_paths
        ]
        areas = top_areas(changed_paths)
        recent_commits, style_info = collect_recent_commits(repo, args.recent)
        staged_stat = decode(git(repo, "diff", "--cached", "--stat", "--compact-summary").stdout)
        unstaged_stat = decode(git(repo, "diff", "--stat", "--compact-summary").stdout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary_lines = [
        f"- repo: {repo_root}",
        f"- branch: {branch}",
        f"- staged entries: {counts.get('staged', 0)}",
        f"- unstaged entries: {counts.get('unstaged', 0)}",
        f"- untracked entries: {counts.get('untracked', 0)}",
    ]
    if areas:
        summary_lines.append(f"- focus areas: {', '.join(areas)}")

    style_lines = [
        f"- preferred style hint: {style_info['style']}",
        f"- conventional subjects: {style_info['conventional_count']}/{style_info['total']}",
        f"- recent commits with body: {style_info['body_count']}/{style_info['total']}",
    ]
    if style_info["types"]:
        type_summary = ", ".join(f"{name} ({count})" for name, count in style_info["types"])
        style_lines.append(f"- common conventional types: {type_summary}")
    if style_info["scopes"]:
        scope_summary = ", ".join(f"{name} ({count})" for name, count in style_info["scopes"])
        style_lines.append(f"- common scopes: {scope_summary}")

    commit_lines = [f"- {short_hash} {subject}" for short_hash, subject, _ in recent_commits]
    suggestion_lines = [
        "- default to a detailed multi-line message",
        "- keep the subject imperative and under 72 characters",
        "- include a `Tests:` line with the command you ran or `not run`",
    ]
    if style_info["style"] == "conventional":
        suggestion_lines.insert(0, "- use a conventional commit subject if the change has a clear type")
    else:
        suggestion_lines.insert(0, "- match the repository's free-form subject style unless the user requests otherwise")

    print("# Git Commit Context")
    print()
    print(format_block("Working Tree Summary", summary_lines))
    print(format_block("Changed Paths", changed_lines))
    print(format_block("Potentially Sensitive Paths", [f"- {path}" for path in sensitive_paths]))
    print(format_block("Review Before Staging", [f"- {path}" for path in review_paths]))
    print(format_block("Commit Style Hint", style_lines))
    print(format_block("Recent Commit Subjects", commit_lines))
    print(format_block("Staged Diff Stat", staged_stat.splitlines() if staged_stat else []))
    print(format_block("Unstaged Diff Stat", unstaged_stat.splitlines() if unstaged_stat else []))
    print(format_block("Suggested Message Shape", suggestion_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
