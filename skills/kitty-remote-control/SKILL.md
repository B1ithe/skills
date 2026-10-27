---
name: kitty-remote-control
description: Control a running kitty terminal through kitty remote control. Use when the user asks to read visible terminal text or scrollback, inspect the last command output, list or focus kitty windows/tabs, create splits/tabs/OS windows, resize panes, change layouts, scroll, rename, send terminal input, or close kitty windows/tabs. Supports explicit --to addresses, KITTY_LISTEN_ON, and safe local socket discovery when the agent runs outside kitty.
---

# Kitty Remote Control

Use the bundled Python CLI for common operations. It wraps `kitten @`, discovers usable local sockets, summarizes `ls` without dumping environment variables, and limits long scrollback reads by default.

## Resolve the command path

Set `<skill-dir>` to the directory containing this `SKILL.md`, then run from the user's current project directory:

```bash
python3 <skill-dir>/scripts/kitty_rc.py [--to ADDRESS] <command> ...
```

Connection order: explicit `--to`, `KITTY_LISTEN_ON`, the controlling kitty terminal, then discovered local sockets. If multiple discovered instances respond, rerun with an explicit `--to`; do not guess. Never pass passwords on a command line. kitty's normal `rc-pass` file or `KITTY_RC_PASSWORD` handling remains available.

Start with a read-only connection and inventory:

```bash
python3 <skill-dir>/scripts/kitty_rc.py doctor
python3 <skill-dir>/scripts/kitty_rc.py list
```

If connection fails, report the diagnostic. With the user's permission, suggest this minimal `kitty.conf` setup and restart kitty; do not edit or restart automatically:

```conf
allow_remote_control socket-only
listen_on unix:/tmp/kitty-agent
```

Then use `--to unix:/tmp/kitty-agent`. Use `allow_remote_control yes` only if the installed kitty does not support `socket-only` or non-socket remote control is actually needed.

## Read before acting

List windows and read text without changing terminal state:

```bash
# Compact inventory; JSON omits environment, layout_state, and other bulky fields
python3 <skill-dir>/scripts/kitty_rc.py list --json

# Last focused window, visible screen
python3 <skill-dir>/scripts/kitty_rc.py read

# Window ID 9, visible screen
python3 <skill-dir>/scripts/kitty_rc.py read 9

# Last command output; requires kitty shell integration
python3 <skill-dir>/scripts/kitty_rc.py read 9 --extent last_cmd_output

# Screen plus scrollback, last 300 lines; --lines 0 means unlimited
python3 <skill-dir>/scripts/kitty_rc.py read 9 --extent all --lines 300

# Machine-readable text and truncation metadata
python3 <skill-dir>/scripts/kitty_rc.py read 9 --extent screen --json
```

Default extent is `screen`; default target is `state:focused`. Prefer numeric IDs from `list` for repeated operations. Other match expressions such as `recent:0`, `title:pattern`, `cwd:pattern`, and `state:active` are passed to kitty unchanged. `num:` is positional, not a stable ID. Do not use `all` unless the user explicitly wants every matching window.

Reading terminal text can expose secrets. Return only relevant excerpts, never environment dumps, and do not repeat credentials or tokens found on screen.

## Adjust windows and tabs

```bash
# Focus
python3 <skill-dir>/scripts/kitty_rc.py focus-window 9
python3 <skill-dir>/scripts/kitty_rc.py focus-tab 3

# Split in the active tab; launch prints the new window ID
python3 <skill-dir>/scripts/kitty_rc.py launch --type window --location vsplit --cwd current
python3 <skill-dir>/scripts/kitty_rc.py launch --type window --location hsplit --title tests -- npm test

# New tab or OS window
python3 <skill-dir>/scripts/kitty_rc.py launch --type tab --tab-title work
python3 <skill-dir>/scripts/kitty_rc.py launch --type os-window --title logs --keep-focus

# Resize by terminal cells; negative increments shrink
python3 <skill-dir>/scripts/kitty_rc.py resize-window 9 --axis horizontal --increment 5
python3 <skill-dir>/scripts/kitty_rc.py resize-window 9 --axis vertical --increment -3
python3 <skill-dir>/scripts/kitty_rc.py resize-window 9 --axis reset

# Layout and scrolling
python3 <skill-dir>/scripts/kitty_rc.py layout splits --tab 3
python3 <skill-dir>/scripts/kitty_rc.py last-layout --tab 3
python3 <skill-dir>/scripts/kitty_rc.py scroll-window 9 1p-
python3 <skill-dir>/scripts/kitty_rc.py scroll-window 9 end

# Rename
python3 <skill-dir>/scripts/kitty_rc.py title-window 9 tests
python3 <skill-dir>/scripts/kitty_rc.py title-tab 3 development
```

`launch` executes arguments directly without a shell. Put options before `--`; everything after `--` is the child command. `vsplit`, `hsplit`, and `split` locations require the `splits` layout. Set that layout first when directional splitting is requested.

After a mutation, verify with `list`, `read`, or the returned new window ID. A successful process exit alone does not prove the visual result. Report what changed and what was verified.

## Terminal input and destructive actions

Sending input can execute commands, change remote systems, or expose secrets. Closing windows/tabs can terminate running work. Obtain explicit user approval for the exact target and impact before these actions unless the user's current request already clearly authorizes that exact action.

```bash
# Send literal text without executing it
python3 <skill-dir>/scripts/kitty_rc.py send-text 9 'git status'

# Send text plus Enter; this can execute a command
python3 <skill-dir>/scripts/kitty_rc.py send-text 9 'git status' --enter

# Numeric IDs are mandatory for close operations
python3 <skill-dir>/scripts/kitty_rc.py close-window 9
python3 <skill-dir>/scripts/kitty_rc.py close-tab 3
```

Prefer reading the target immediately before sending input or closing it. Never send to `all`; the CLI rejects it. After a timeout or uncertain mutation, inspect state before retrying to avoid duplicate input or effects.

## Advanced operations

For operations not covered by the CLI, use the installed version's own help first, then `kitten @ --to ADDRESS ...`. Do not guess flags. Keep the same target-selection, privacy, approval, and verification rules. Useful commands include `detach-window`, `detach-tab`, `resize-os-window`, `set-enabled-layouts`, `set-spacing`, and `action`.
