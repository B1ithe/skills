# MuMuTool CLI reference

## Contents

- Environment and discovery
- Output and targeting
- Instance commands
- App and Android control
- Configuration keys
- ADB workflows
- Failure handling
- Sources

## Environment and discovery

The official developer documentation requires MuMuPlayer for Mac 1.5.4 or newer. The CLI is bundled inside the app:

```text
/Applications/MuMuPlayer.app/Contents/MacOS/mumutool
```

Open MuMuPlayer → Developer → Open Command-Line Tool to access the same executable. Resolve `MUMUTOOL_SKILL_DIR` to the absolute directory containing `SKILL.md`; its wrapper at `"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh"` handles the normal path and these overrides:

- `MUMUTOOL_PATH`: full path to `mumutool`
- `MUMUPLAYER_APP`: path to `MuMuPlayer.app`

Check availability:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" --version
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" port
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" info all
```

The command reference below was verified against MuMuPlayer 1.8.15 and `mumutool` 1.0.0.

## Output and targeting

Most commands emit JSON. A successful outer response normally has:

```json
{"errcode": 0, "message": "", "return": {}}
```

`control` responses can also contain `return.callback.errcode`, `message`, and action-specific data. Check both error layers.

Commands that accept `<device>` support:

- `0`: one instance
- `0,2,4`: selected instances
- `all`: all instances

`info <device>` returns fields such as `index`, `name`, `state`, `pid`, `adb_port`, `bundle_path`, and `state_detail`. ADB and Android commands require `state` to be `running` and a non-empty `adb_port`.

## Instance commands

| Operation | Syntax | Notes |
|---|---|---|
| Server port | `mumutool port` | If unavailable, later commands will not work. |
| Instance info | `mumutool info <device>` | Read-only readiness and ADB discovery. |
| Create | `mumutool create [--count N] [--type tablet\|phone] [--setting JSON_OR_FILE]` | `--count` is for creating at least 2; settings override conflicting type defaults. |
| Clone | `mumutool clone <device>` | Creates copies of selected instances. |
| Delete | `mumutool delete <device>` | Permanently removes instance data. |
| Open | `mumutool open <device>` | Starts selected instances. |
| Close | `mumutool close <device>` | Stops selected instances. |
| Restart | `mumutool restart <device>` | Restarts selected instances. |
| Configure | `mumutool config <device> --setting JSON_OR_FILE` | Some values take effect on next launch. |
| Import | `mumutool import [--count N] --path FILE.mad [--path FILE2.mad ...]` | With count ≥2, clone from the imported archive. |
| Export | `mumutool export <device> [--dir DIR]` | Exports `.mad` instance archives. |
| Move data | `mumutool move <device> [--dir DIR]` | Moves instance storage. |
| Show | `mumutool show` | Shows all MuMuPlayer and device windows. |
| Hide | `mumutool hide` | Hides all MuMuPlayer and device windows. |

Examples:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" create --type phone
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" create --setting '{"vmCpuCount":4,"vmMemoryOfMB":4096}'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" config 0 --setting /absolute/path/settings.json
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" export 0 --dir /absolute/path/backups
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" import --path /absolute/path/instance.mad
```

## App and Android control

General syntax:

```text
mumutool control <device> --action ACTION [--package PACKAGE] [--path PATH] [--type TYPE] [--cmd CMD]
```

Actions:

| Action | Required option | Purpose |
|---|---|---|
| `open_app` | `--package` | Launch a package. |
| `close_app` | `--package` | Force-stop a package. |
| `install_apk` | `--path` | Install `.apk`, `.apks`, or `.xapk`. |
| `uninstall_app` | `--package` | Uninstall a package. |
| `app_status` | `--package` | Return app status. |
| `run_cmd` | `--cmd` | Run an Android shell command and return output. |
| `run_tool` | `--type` | Invoke a MuMu toolbar action. |

Toolbar types exposed by MuMuPlayer 1.8.15:

```text
goBack
goHome
showActivity
showVolumePanel
addVolume
reduceVolume
muteVolume
rotation
shake
vibration
```

Examples:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'wm size'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'input tap 300 400'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'input swipe 500 1500 500 400 500'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_cmd --cmd 'input keyevent 3'
"$MUMUTOOL_SKILL_DIR/scripts/mumutool.sh" control 0 --action run_tool --type goHome
```

## Configuration keys

Pass configuration as an inline JSON object or an absolute JSON file path. Common official keys:

| Key | Example | Meaning |
|---|---:|---|
| `vmName` | `"Android Device"` | Instance name |
| `vmCpuCount` | `4` | CPU cores |
| `vmMemoryOfMB` | `4096` | RAM in MB |
| `resolutionWidthHeight` | `"1600x900"` | Display resolution |
| `resolutionDPI` | `240` | Display density |
| `maxFpsLimit` | `144` | Maximum FPS |
| `dynamicFpsEnable` | `false` | Dynamic FPS |
| `dynamicFpsLimitToLow` | `15` | Background FPS |
| `fpsShowEnable` | `false` | FPS counter |
| `renderQualityEnable` | `false` | Graphics enhancement |
| `gpuFastMathEnable` | `false` | GPU fast math |
| `gpuPropModel` | `"Adreno (TM) 640"` | Reported GPU |
| `phonePropBrand` | `"Redmi"` | Reported brand |
| `phonePropModel` | `"K60 Ultra"` | Reported model name |
| `phonePropMiit` | `"23078RKD5C"` | Reported model identifier |
| `phonePropIMEI` | string | Reported IMEI |
| `simulationProps` | `"android_id=123456"` | Simulated Android ID |
| `macAddress` | string | Reported MAC address |
| `locationLatitude` | string | Simulated latitude |
| `locationLongtitude` | string | Simulated longitude; official key uses this spelling |
| `locationMetersElevation` | string | Simulated elevation |
| `vmRootEnable` | `false` | Root access |
| `systemWritable` | `false` | Writable system disk |
| `usingNormalADBPort` | `true` | Normal ADB port behavior |
| `customAdbPort` | `16384` | Custom ADB port |
| `displayCutout` | `0` | Notch display |
| `windowAutoRotationEnable` | `true` | Auto rotation |
| `trackCursorEnable` | `false` | MuMu cursor style |
| `bossKeyEnable` | `true` | Boss key |
| `exitConfirmEnable` | `true` | Exit confirmation |

Treat device identifiers, simulated location, root, writable system, storage movement, and ADB port changes as sensitive configuration.

## ADB workflows

`"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" <index> ...` reads `adb_port` from `mumutool info`, connects to `127.0.0.1:<port>`, and targets that serial.

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 get-state
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell wm size
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell pm list packages -3
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell dumpsys window
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 logcat -d -t 200
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 push /absolute/path/local.txt /sdcard/Download/local.txt
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 pull /sdcard/Download/result.txt /absolute/path/result.txt
```

Capture a screenshot:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-screenshot.sh" 0 /absolute/workspace/path/tmp/mumutool-skill/screen.png
```

Hierarchy inspection:

```bash
MUMUTOOL_SKILL_DIR="/absolute/path/from-the-skill-locator"
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 shell uiautomator dump /sdcard/window.xml
"$MUMUTOOL_SKILL_DIR/scripts/mumu-adb.sh" 0 pull /sdcard/window.xml /absolute/workspace/path/tmp/mumutool-skill/window.xml
```

## Failure handling

- Missing executable or `port` failure: follow [Troubleshooting](../SKILL.md#troubleshooting) for path checks, task-required launch, and bounded recovery. Do not infer installation permission from a request to control an existing instance.
- Missing `adb_port`: the instance is not ready.
- ADB `offline`: wait for `state: running`, reconnect, then retry.
- Top-level success but failed action: inspect `return.callback`.
- Configuration appears unchanged: check whether the key requires the next launch.
- Coordinate action misses: take a fresh screenshot and query `wm size`; orientation may have changed.

## Sources

- Official MuMuPlayer for Mac developer documentation: https://www.mumuplayer.com/help/mac/developer-support-function.html
- Installed CLI help: `mumutool --help` and `mumutool help <subcommand>`
