---
name: mumutool-skill
description: Control MuMuPlayer for Mac with its bundled mumutool CLI and ADB. Use when Grok/Codex needs to discover, inspect, create, clone, open, close, restart, configure, import, export, move, show, or hide MuMu Android instances; manage Android apps; capture screenshots; tap, swipe, enter text, press keys, run Android shell commands, or automate UI inside a MuMuPlayer macOS instance. Trigger on mentions of MuMuPlayer for Mac, MuMuPlayer Pro, mumutool, MuMu emulator instances, or MuMu ADB ports.
---

# MuMuTool Skill

Control MuMuPlayer for Mac through the bundled `mumutool` executable. Use `mumutool` for instance lifecycle and app management; use ADB for screenshots, UI inspection, and fine-grained Android interaction.

This skill is macOS-only. Do not substitute the Windows-only `mumu-cli.exe` or `MuMuManager.exe`.

## Resolve bundled paths

Get the absolute directory containing this `SKILL.md` from the skill locator and assign it in every shell invocation:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
```

Run bundled scripts through `"$MUMUTOOL_SKILL_DIR/scripts/..."`. Never assume `scripts/` exists under the repository root or the current working directory. Shell variables do not persist across separate tool calls, so either assign `MUMUTOOL_SKILL_DIR` again or use the resolved absolute script path directly.

Resolve bundled references against the same directory. Write generated artifacts, including screenshots and hierarchy dumps, to an explicit absolute path in the user's workspace rather than into the skill directory.

## Preflight

1. Run `"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" port`.
2. Stop if the command cannot return a server port. MuMuPlayer must be installed and its control service available.
3. Run `"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" info all`.
4. Select the intended instance by `index`. Do not assume index `0` when multiple instances exist.
5. Require `state: "running"` before app, shell, ADB, or UI operations. Open the instance first if the user requested an operation that needs Android running.
6. Inspect both top-level `errcode` and nested `return.callback.errcode` when present.

MuMuPlayer for Mac 1.5.4 or newer is required by the official documentation. The usual binary path is:

```text
/Applications/MuMuPlayer.app/Contents/MacOS/mumutool
```

Use `"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh"` instead of hard-coding that path. It also honors `MUMUTOOL_PATH` and `MUMUPLAYER_APP`.

## Choose the control layer

- Use `mumutool` for instance lifecycle, configuration, backup/import, data movement, visibility, app lifecycle, APK installation, toolbar actions, and short Android shell commands.
- Use `"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh"` for screenshots, file transfer, package inspection, hierarchy dumps, logs, and commands whose output or quoting is easier through ADB.
- Use `"$MUMUTOOL_SKILL_DIR/scripts/mumu-screenshot.sh"` before coordinate-based UI actions and again afterward to verify the result.

Read [references/cli-reference.md](references/cli-reference.md), resolved relative to `MUMUTOOL_SKILL_DIR`, before creating, configuring, importing, exporting, moving, or deleting instances, or when exact flags and configuration keys are needed.

## Manage instances

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" info all
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" open 0
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" close 0
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" restart 0
```

Targets accept one index (`0`), comma-separated indexes (`0,2`), or `all`. Use `all` only when the user explicitly asks for every instance.

After lifecycle changes, poll `info <index>` until the requested state appears. Do not send Android commands merely because the host process exists.

## Manage apps

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action app_status --package com.example.app
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action open_app --package com.example.app
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action close_app --package com.example.app
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action install_apk --path /absolute/path/app.apk
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action uninstall_app --package com.example.app
```

Verify package names rather than guessing:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell pm list packages -3
```

## Automate the Android UI

Follow this loop:

1. Capture a screenshot.
2. Inspect visible content. Dump the accessibility hierarchy when useful.
3. Choose a stable selector or coordinates.
4. Perform exactly one logical interaction.
5. Capture another screenshot and verify the expected state.

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
OUTPUT_DIR="/absolute/path/in-the-user-workspace/tmp/mumutool-skill"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-screenshot.sh" 0 "$OUTPUT_DIR/before.png"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell uiautomator dump /sdcard/window.xml
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 pull /sdcard/window.xml "$OUTPUT_DIR/window.xml"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'input tap 540 960'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'input swipe 540 1400 540 400 500'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_tool --type goBack
"$MUMUTOOL_SKILL_DIR/scripts/mumu-screenshot.sh" 0 "$OUTPUT_DIR/after.png"
```

Raw `input text` is reliable mainly for ASCII. Do not promise correct Unicode or Chinese input through that command; use an installed Unicode-capable ADB IME or accessibility automation when required.

## Safety rules

- Treat `delete`, `move`, `import`, `config`, `uninstall_app`, destructive `run_cmd` calls, and bulk target `all` as state-changing operations. Execute them only when explicitly requested.
- Never tap, swipe, or type without a current screenshot or hierarchy scan.
- Prefer a specific instance index and package name.
- Preserve user data. Export an instance before deletion when the user asks for a backup or preservation is otherwise in scope.
- Do not restart merely to apply a configuration unless the user requested the configuration change and a restart is needed.
- Pass `--cmd` as one quoted argument. Never interpolate untrusted text into an Android shell command.
- Avoid repeating sensitive screen content, identifiers, or account data in status messages unless necessary.
- Verify every mutation with `info`, `app_status`, a screenshot, or an equivalent read-only check.

## Troubleshooting

- If `mumutool` is missing, verify MuMuPlayer for Mac is installed, or set `MUMUTOOL_PATH` to the executable.
- If `port` fails, launch MuMuPlayer and retry.
- If `info` shows a stopped instance, run `open <index>` only when required by the task, then poll readiness.
- If ADB is unavailable, install Android platform tools or set `ADB` to its executable path.
- If ADB is offline, retry `adb connect 127.0.0.1:<adb_port>` after the instance reaches `running`.
- If a UI command has no visible effect, take a fresh screenshot, confirm orientation and physical screen size, then recalculate coordinates.
