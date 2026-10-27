#!/usr/bin/env python3
"""Safe, compact helpers for kitty remote control (standard library only)."""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any


EXTENTS = (
    "screen",
    "all",
    "alternate",
    "alternate_scrollback",
    "first_cmd_output_on_screen",
    "last_cmd_output",
    "last_non_empty_output",
    "last_visited_cmd_output",
    "selection",
)


class KittyError(RuntimeError):
    pass


class Kitty:
    def __init__(self, address: str | None, timeout: float) -> None:
        self.requested_address = address or os.environ.get("KITTY_LISTEN_ON") or None
        self.address_source = (
            "explicit" if address else "environment" if self.requested_address else ""
        )
        self.timeout = timeout
        self.kitten = shutil.which("kitten")
        if not self.kitten:
            for candidate in (
                "/Applications/kitty.app/Contents/MacOS/kitten",
                "/opt/homebrew/bin/kitten",
                "/usr/local/bin/kitten",
            ):
                if os.access(candidate, os.X_OK):
                    self.kitten = candidate
                    break
        if not self.kitten:
            raise KittyError("kitten executable not found; install kitty or add it to PATH")
        self._resolved = False
        self.address: str | None = None
        self._tree: list[dict[str, Any]] | None = None

    def _raw(
        self,
        address: str | None,
        arguments: list[str],
        *,
        timeout: float | None = None,
        input_text: str | None = None,
    ) -> str:
        command = [self.kitten or "kitten", "@"]
        if address:
            command.extend(("--to", address))
        command.extend(arguments)
        try:
            result = subprocess.run(
                command,
                input=input_text,
                stdin=subprocess.DEVNULL if input_text is None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KittyError(f"kitty remote control timed out: {' '.join(arguments[:2])}") from exc
        except OSError as exc:
            raise KittyError(f"could not run kitten: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown kitty error"
            raise KittyError(detail)
        return result.stdout

    @staticmethod
    def _parse_tree(output: str) -> list[dict[str, Any]]:
        try:
            tree = json.loads(output)
        except json.JSONDecodeError as exc:
            raise KittyError("kitten @ ls returned invalid JSON") from exc
        if not isinstance(tree, list):
            raise KittyError("kitten @ ls returned an unexpected structure")
        return tree

    def _probe(self, address: str | None, timeout: float) -> list[dict[str, Any]]:
        return self._parse_tree(self._raw(address, ["ls"], timeout=timeout))

    @staticmethod
    def _socket_candidates() -> list[str]:
        paths: set[str] = set()
        lsof = shutil.which("lsof")
        if lsof:
            try:
                result = subprocess.run(
                    [lsof, "-nP", "-U", "-a", "-c", "kitty"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=4,
                    check=False,
                )
                for line in result.stdout.splitlines()[1:]:
                    fields = line.split()
                    if fields and fields[-1].startswith("/"):
                        paths.add(fields[-1])
            except (OSError, subprocess.TimeoutExpired):
                pass

        patterns = ["/tmp/kitty*"]
        if os.environ.get("TMPDIR"):
            patterns.append(os.path.join(os.environ["TMPDIR"], "kitty*"))
        for pattern in patterns:
            for path in glob.glob(pattern):
                try:
                    if stat.S_ISSOCK(os.stat(path).st_mode):
                        paths.add(path)
                except OSError:
                    continue

        usable = []
        for path in sorted(paths):
            name = os.path.basename(path)
            if name.startswith("kitty-ipc-") or "kitty" not in name.lower():
                continue
            usable.append("unix:" + path)
        return usable

    def _resolve(self) -> None:
        if self._resolved:
            return
        if self.requested_address:
            self._tree = self._probe(self.requested_address, self.timeout)
            self.address = self.requested_address
            self._resolved = True
            return

        direct_error = ""
        try:
            self._tree = self._probe(None, min(3.0, self.timeout))
            self.address = None
            self.address_source = "controlling-terminal"
            self._resolved = True
            return
        except KittyError as exc:
            direct_error = str(exc)

        reachable: list[tuple[str, list[dict[str, Any]]]] = []
        candidates = self._socket_candidates()
        for candidate in candidates:
            try:
                tree = self._probe(candidate, min(2.0, self.timeout))
                reachable.append((candidate, tree))
            except KittyError:
                continue
        if len(reachable) == 1:
            self.address, self._tree = reachable[0]
            self.address_source = "discovered"
            self._resolved = True
            return
        if len(reachable) > 1:
            addresses = ", ".join(address for address, _ in reachable)
            raise KittyError(f"multiple kitty instances responded; choose one with --to: {addresses}")

        candidate_note = ", ".join(candidates) if candidates else "no candidate sockets found"
        raise KittyError(
            "kitty remote control is unavailable. "
            f"Direct connection: {direct_error or 'failed'}; discovery: {candidate_note}. "
            "Configure 'allow_remote_control socket-only' and "
            "'listen_on unix:/tmp/kitty-agent' in kitty.conf, restart kitty, "
            "then pass --to unix:/tmp/kitty-agent."
        )

    def run(self, arguments: list[str], *, input_text: str | None = None) -> str:
        self._resolve()
        return self._raw(self.address, arguments, input_text=input_text)

    def tree(self) -> list[dict[str, Any]]:
        self._resolve()
        if self._tree is None:
            self._tree = self._parse_tree(self.run(["ls"]))
        return self._tree


def match(value: str | int, kind: str = "window") -> str:
    text = str(value)
    if re.fullmatch(r"-?\d+", text):
        return f"id:{text}"
    if not text.strip():
        raise KittyError(f"empty {kind} match expression")
    return text


def numeric_id(value: str) -> str:
    if not re.fullmatch(r"[1-9]\d*", value):
        raise argparse.ArgumentTypeError("must be a positive numeric kitty ID")
    return value


def non_negative(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def flatten(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for os_window in tree:
        for tab in os_window.get("tabs", []):
            for window in tab.get("windows", []):
                foreground = window.get("foreground_processes") or []
                process = foreground[-1] if foreground else {}
                rows.append(
                    {
                        "os_window_id": os_window.get("id"),
                        "os_window_active": os_window.get("is_active", False),
                        "os_window_focused": os_window.get("is_focused", False),
                        "tab_id": tab.get("id"),
                        "tab_title": tab.get("title", ""),
                        "tab_active": tab.get("is_active", False),
                        "tab_focused": tab.get("is_focused", False),
                        "layout": tab.get("layout", ""),
                        "enabled_layouts": tab.get("enabled_layouts", []),
                        "window_id": window.get("id"),
                        "window_title": window.get("title", ""),
                        "window_active": window.get("is_active", False),
                        "window_focused": window.get("is_focused", False),
                        "at_prompt": window.get("at_prompt"),
                        "in_alternate_screen": window.get("in_alternate_screen", False),
                        "columns": window.get("columns"),
                        "lines": window.get("lines"),
                        "cwd": process.get("cwd") or window.get("cwd", ""),
                        "pid": process.get("pid") or window.get("pid"),
                        "cmdline": window.get("cmdline", []),
                        "last_reported_cmdline": window.get("last_reported_cmdline", ""),
                        "last_cmd_exit_status": window.get("last_cmd_exit_status"),
                    }
                )
    return rows


def flags(item: dict[str, Any], prefix: str = "") -> str:
    values = []
    if item.get(prefix + "active"):
        values.append("active")
    if item.get(prefix + "focused"):
        values.append("focused")
    return ",".join(values) or "-"


def print_inventory(tree: list[dict[str, Any]]) -> None:
    for os_window in tree:
        print(f"OS {os_window.get('id')} [{flags(os_window, 'is_')}]")
        for tab in os_window.get("tabs", []):
            print(
                f"  TAB {tab.get('id')} [{flags(tab, 'is_')}] "
                f"layout={tab.get('layout', '')} title={tab.get('title', '')}"
            )
            for window in tab.get("windows", []):
                foreground = window.get("foreground_processes") or []
                process = foreground[-1] if foreground else {}
                cwd = process.get("cwd") or window.get("cwd", "")
                command = " ".join(window.get("cmdline") or [])
                print(
                    f"    WIN {window.get('id')} [{flags(window, 'is_')}] "
                    f"{window.get('columns', '?')}x{window.get('lines', '?')} "
                    f"title={window.get('title', '')} cwd={cwd} cmd={command}"
                )


def action(kitty: Kitty, arguments: list[str], *, input_text: str | None = None) -> None:
    output = kitty.run(arguments, input_text=input_text).strip()
    print(output if output else "OK")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="kitty remote control address, e.g. unix:/tmp/kitty-agent")
    parser.add_argument("--timeout", type=float, default=10.0, help="command timeout in seconds")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check the remote control connection")
    list_parser = sub.add_parser("list", help="list windows without environment variables")
    list_parser.add_argument("--json", action="store_true")

    read = sub.add_parser("read", help="read terminal text")
    read.add_argument("window", nargs="?", default="state:focused")
    read.add_argument("--extent", choices=EXTENTS, default="screen")
    read.add_argument("--lines", type=non_negative, default=200, help="tail lines; 0 is unlimited")
    read.add_argument("--json", action="store_true")

    focus_window = sub.add_parser("focus-window")
    focus_window.add_argument("window")
    focus_tab = sub.add_parser("focus-tab")
    focus_tab.add_argument("tab")

    launch = sub.add_parser("launch", help="launch a window, tab, or OS window")
    launch.add_argument("--type", choices=("window", "tab", "os-window"), default="window")
    launch.add_argument("--match", dest="tab_match")
    launch.add_argument("--title")
    launch.add_argument("--tab-title")
    launch.add_argument("--cwd")
    launch.add_argument(
        "--location",
        choices=("default", "after", "before", "first", "hsplit", "last", "neighbor", "split", "vsplit"),
        default="default",
    )
    launch.add_argument("--bias", type=int)
    launch.add_argument("--keep-focus", action="store_true")
    launch.add_argument("--source-window")
    launch.add_argument("--next-to")
    launch.add_argument("child", nargs=argparse.REMAINDER)

    resize = sub.add_parser("resize-window")
    resize.add_argument("window")
    resize.add_argument("--axis", choices=("horizontal", "vertical", "reset"), default="horizontal")
    resize.add_argument("--increment", type=int, default=2)

    layout = sub.add_parser("layout")
    layout.add_argument("name")
    layout.add_argument("--tab")
    last_layout = sub.add_parser("last-layout")
    last_layout.add_argument("--tab")

    scroll = sub.add_parser("scroll-window")
    scroll.add_argument("window")
    scroll.add_argument("amount", help="for example 5, 1p-, start, end, or 1r")

    send = sub.add_parser("send-text")
    send.add_argument("window")
    send.add_argument("text")
    send.add_argument("--enter", action="store_true")
    send.add_argument("--bracketed-paste", choices=("disable", "auto", "enable"), default="disable")

    close_window = sub.add_parser("close-window")
    close_window.add_argument("window", type=numeric_id)
    close_tab = sub.add_parser("close-tab")
    close_tab.add_argument("tab", type=numeric_id)

    title_window = sub.add_parser("title-window")
    title_window.add_argument("window")
    title_window.add_argument("title")
    title_window.add_argument("--temporary", action="store_true")
    title_tab = sub.add_parser("title-tab")
    title_tab.add_argument("tab")
    title_tab.add_argument("title")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        raise KittyError("--timeout must be greater than zero")
    kitty = Kitty(args.to, args.timeout)

    if args.command == "doctor":
        tree = kitty.tree()
        version = subprocess.run(
            [kitty.kitten or "kitten", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout,
            check=False,
        ).stdout.strip()
        rows = flatten(tree)
        print(f"kitten: {kitty.kitten}")
        print(f"version: {version}")
        print(f"address: {kitty.address or '<controlling terminal>'} ({kitty.address_source})")
        print(f"os_windows: {len(tree)}")
        print(f"tabs: {len({row['tab_id'] for row in rows})}")
        print(f"windows: {len(rows)}")
        return 0

    if args.command == "list":
        tree = kitty.tree()
        if args.json:
            print(json.dumps({"address": kitty.address, "windows": flatten(tree)}, ensure_ascii=False, indent=2))
        else:
            print_inventory(tree)
        return 0

    if args.command == "read":
        target = match(args.window)
        text = kitty.run(["get-text", "--match", target, "--extent", args.extent])
        lines = text.splitlines()
        total = len(lines)
        truncated = bool(args.lines and total > args.lines)
        shown = lines[-args.lines :] if truncated else lines
        content = "\n".join(shown)
        if text.endswith("\n") and content:
            content += "\n"
        if args.json:
            print(
                json.dumps(
                    {
                        "window": target,
                        "extent": args.extent,
                        "total_lines": total,
                        "returned_lines": len(shown),
                        "truncated": truncated,
                        "text": content,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if truncated:
                print(
                    f"[showing last {len(shown)} of {total} lines; use --lines 0 for all]",
                    file=sys.stderr,
                )
            sys.stdout.write(content)
        return 0

    if args.command == "focus-window":
        action(kitty, ["focus-window", "--match", match(args.window)])
    elif args.command == "focus-tab":
        action(kitty, ["focus-tab", "--match", match(args.tab, "tab")])
    elif args.command == "launch":
        command = ["launch", "--type", args.type, "--location", args.location]
        options = (
            ("--match", match(args.tab_match, "tab") if args.tab_match else None),
            ("--title", args.title),
            ("--tab-title", args.tab_title),
            ("--cwd", args.cwd),
            ("--bias", str(args.bias) if args.bias is not None else None),
            ("--source-window", match(args.source_window) if args.source_window else None),
            ("--next-to", match(args.next_to) if args.next_to else None),
        )
        for option, value in options:
            if value is not None:
                command.extend((option, value))
        if args.keep_focus:
            command.append("--keep-focus")
        child = list(args.child)
        if child and child[0] == "--":
            child.pop(0)
        action(kitty, command + child)
    elif args.command == "resize-window":
        action(
            kitty,
            [
                "resize-window",
                "--match",
                match(args.window),
                "--axis",
                args.axis,
                "--increment",
                str(args.increment),
            ],
        )
    elif args.command == "layout":
        command = ["goto-layout"]
        if args.tab:
            command.extend(("--match", match(args.tab, "tab")))
        action(kitty, command + [args.name])
    elif args.command == "last-layout":
        command = ["last-used-layout"]
        if args.tab:
            command.extend(("--match", match(args.tab, "tab")))
        action(kitty, command)
    elif args.command == "scroll-window":
        action(kitty, ["scroll-window", "--match", match(args.window), args.amount])
    elif args.command == "send-text":
        target = match(args.window)
        if target == "all":
            raise KittyError("send-text refuses target 'all'; select a specific window")
        text = args.text + ("\n" if args.enter else "")
        action(
            kitty,
            [
                "send-text",
                "--match",
                target,
                "--stdin",
                "--bracketed-paste",
                args.bracketed_paste,
            ],
            input_text=text,
        )
    elif args.command == "close-window":
        action(kitty, ["close-window", "--match", match(args.window)])
    elif args.command == "close-tab":
        action(kitty, ["close-tab", "--match", match(args.tab, "tab")])
    elif args.command == "title-window":
        command = ["set-window-title", "--match", match(args.window)]
        if args.temporary:
            command.append("--temporary")
        action(kitty, command + [args.title])
    elif args.command == "title-tab":
        action(kitty, ["set-tab-title", "--match", match(args.tab, "tab"), args.title])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KittyError as exc:
        print(f"kitty-rc: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
