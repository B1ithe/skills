---
name: ssh-skill
description: Use this skill for agent-accessible SSH operations through a CLI-first interface, including direct username/password connections, direct private-key connections, saved project profiles, non-interactive remote command execution with daemon reuse, interactive PTY commands and shells, SFTP upload/download, and connection tests.
---

# SSH Skill

Use this skill for project-local SSH work from any agent that can read `SKILL.md` and run shell commands. The stable interface is the CLI; platform metadata is optional.

## Requirements

- `bash`
- `uv`, or Python 3.11+ with Paramiko already installed
- One SSH target source:
  - A direct hostname/IP with explicit `--username` and either `--password` or `--identity-file`
  - A saved project profile
  - A matching daemon for `exec`, keyed by hostname, port, and username

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. The launcher prefers `uv run --locked`; when `uv` is unavailable, it falls back to `python3` then `python` without installing packages. The launcher keeps uv's project environment outside the skill directory by default; set `UV_PROJECT_ENVIRONMENT` or `SSH_SKILL_UV_ENVIRONMENT` to override it.

## Command Path

Resolve `<ssh-skill-dir>` from the directory that contains this `SKILL.md` file. Run commands from the current project working directory:

```bash
bash <ssh-skill-dir>/scripts/run.sh <command> ...
```

Do not `cd` into the skill directory just to run commands. The default project root for local state is the current working directory unless `--root` is passed.

The CLI writes one JSON object to stdout for each final result except `interactive`. Transfer progress and diagnostics go to stderr. `interactive` streams the remote terminal directly and returns the remote exit code.

## JSON Contract

Successful CLI operations include:

- `success: true`
- `operation`
- Operation-specific fields

Failures include:

- `success: false`
- `error`
- Optional `detail`

Remote command failures are still valid CLI results: `exec` returns `success: false`, `exit_code`, `stdout`, `stderr`, and `method`. `interactive` can write a small JSON summary to `--summary-file` when machine-readable status is needed.

## Target Resolution

Connection values resolve in this order:

1. A same-name saved profile
2. The target itself as a direct hostname/IP
3. A matching daemon for `exec`, identified by `hostname + port + username`

Direct hostname/IP targets require `--username`. If no matching daemon exists, connection setup also requires exactly one of `--password` or `--identity-file`. `--identity-file` is expanded to an absolute path, must point to an existing file, and is mutually exclusive with `--password`.

This skill does not read or manage `~/.ssh/config`. Pass hostname, username, port, and authentication explicitly, or save them in a project profile.

Unknown host keys are trusted automatically. This favors automation over strict MITM protection.

## Commands

```bash
bash <ssh-skill-dir>/scripts/run.sh list
bash <ssh-skill-dir>/scripts/run.sh find <keyword>
bash <ssh-skill-dir>/scripts/run.sh test <target> --timeout 30
bash <ssh-skill-dir>/scripts/run.sh exec <target> -- "sh -lc 'whoami && hostname'"
bash <ssh-skill-dir>/scripts/run.sh interactive <target> -- "sudo systemctl status nginx"
bash <ssh-skill-dir>/scripts/run.sh interactive <target> --shell
bash <ssh-skill-dir>/scripts/run.sh upload <target> ./local-file /remote/path/
bash <ssh-skill-dir>/scripts/run.sh download <target> /remote/file ./local-file
```

Use `--recursive` for directory upload or download.

Test a direct username/password connection without saving it:

```bash
bash <ssh-skill-dir>/scripts/run.sh \
  test 203.0.113.10 --username root --password "$SSH_PASSWORD" --timeout 30
```

Test a direct private-key connection without saving it:

```bash
bash <ssh-skill-dir>/scripts/run.sh \
  test 203.0.113.10 --username root --identity-file ~/.ssh/id_ed25519 --timeout 30
```

Save a successfully authenticated profile only when the user explicitly asks to remember it:

```bash
bash <ssh-skill-dir>/scripts/run.sh \
  test 203.0.113.10 --username root --identity-file ~/.ssh/id_ed25519 --save --save-as prod
```

Run a command through a saved profile:

```bash
bash <ssh-skill-dir>/scripts/run.sh exec prod -- "hostname"
```

Run a direct command and start a daemon for later reuse:

```bash
bash <ssh-skill-dir>/scripts/run.sh \
  exec 203.0.113.10 --username root --identity-file ~/.ssh/id_ed25519 -- "hostname"
```

Reuse an existing daemon without passing authentication again:

```bash
bash <ssh-skill-dir>/scripts/run.sh exec 203.0.113.10 --username root -- "uptime"
```

Pass `--no-daemon` to force a one-shot direct `exec`. `test`, `interactive`, `upload`, and `download` always open direct SSH connections and do not use or start the daemon.

Run a foreground interactive command when the remote program needs a PTY or live input:

```bash
bash <ssh-skill-dir>/scripts/run.sh interactive prod -- "sudo systemctl restart nginx"
```

Open the remote account's default shell explicitly:

```bash
bash <ssh-skill-dir>/scripts/run.sh interactive prod --shell
```

The `interactive` command:

- Requires local stdin and stdout to be real TTYs.
- Always opens a direct SSH connection; it does not use or start the daemon.
- Sends local input to the remote PTY and streams remote terminal output directly.
- Returns the remote exit code when available, or `255` if the SSH channel closes without one.
- Supports `--username`, `--password`, `--identity-file`, `--port`, `--connect-timeout`, `--session-timeout`, `--term`, `--rows`, and `--cols`.
- Does not support `--save` or `--save-as`; save profiles with `test --save`.
- Accepts local options only before `--`; everything after `--` is the remote command.
- Writes no final JSON to stdout. Use `--summary-file PATH` for a small JSON result file.
- Records no transcript by default. Use `--log-file PATH` to write raw remote terminal output bytes. Existing logs are refused unless `--append-log` or `--overwrite-log` is passed.

Summary and log paths are resolved under the selected project root. `--summary-file` refuses to overwrite an existing file unless `--overwrite-summary` is passed.

List or remove saved project profiles:

```bash
bash <ssh-skill-dir>/scripts/run.sh profiles list
bash <ssh-skill-dir>/scripts/run.sh profiles remove prod
```

Inspect or stop the daemon for a profile:

```bash
bash <ssh-skill-dir>/scripts/run.sh control status prod
bash <ssh-skill-dir>/scripts/run.sh control stop prod
```

Inspect or stop the daemon for a direct host identity:

```bash
bash <ssh-skill-dir>/scripts/run.sh control status 203.0.113.10 --username root --port 22
bash <ssh-skill-dir>/scripts/run.sh control stop 203.0.113.10 --username root --port 22
```

## Project State

Saved profiles and daemon state live under `.ssh-skill/` in the selected project root.

Saved profiles are JSON at `.ssh-skill/profiles.json`. The CLI:

- Creates `.ssh-skill/` with mode `0700`
- Writes `profiles.json` atomically with mode `0600`
- Rejects symlinked profile files and state directories
- Writes `.ssh-skill/.gitignore` with `/profiles.json`
- Never returns passwords from list, find, profile listing, daemon status, or errors
- Returns `identity_file` paths for private-key profiles so users can verify which key a profile uses

Treat password profiles as local plaintext secrets. Do not print, commit, publish, or copy `profiles.json`. Do not expose passwords, private keys, saved profile files, or downloaded secrets in chat.

## Boundaries

- Use this CLI instead of raw `ssh`, `scp`, or `sftp` when the skill is available.
- Use `interactive` for commands that require PTY, shell prompts, menus, or interactive sudo.
- Before destructive remote changes, privilege changes, service restarts, data deletion, or broad writes, explain the exact command and expected impact, then get user confirmation.
- Do not create, edit, delete, parse, or manage SSH config entries from this skill.
- Do not use this skill for SSH tunnels, key management, `rsync`, server-to-server copy, or batch host fan-out.
