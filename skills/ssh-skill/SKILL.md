---
name: ssh-skill
description: Use this skill for agent-accessible SSH operations through a CLI-first interface, including SSH config aliases, direct username/password connections, explicit project credential profiles, non-interactive remote command execution, interactive PTY commands and shells, SFTP upload/download, connection tests, and daemon connection reuse.
---

# SSH Skill

Use this skill for project-local SSH work from any agent that can read `SKILL.md` and run shell commands. The stable interface is the CLI; platform metadata is optional.

## Requirements

- `bash`
- `uv`, or Python 3.11+ with Paramiko already installed
- One SSH target source:
  - A `Host` alias in `~/.ssh/config`
  - A direct hostname/IP with connection options
  - A saved project credential profile

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

1. Explicit command options: `--username`, `--password`, and `--port`
2. A same-name project credential profile
3. A same-name `Host` alias from `~/.ssh/config`
4. The target itself as a direct hostname/IP

Use `--password` for direct password authentication. Prefer saved profiles or SSH keys when practical because process listings and shell history may expose command-line passwords.

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

Save a successfully authenticated username/password profile only when the user explicitly asks to remember it:

```bash
bash <ssh-skill-dir>/scripts/run.sh \
  test 203.0.113.10 --username root --password "$SSH_PASSWORD" --save --save-as prod
```

Explicit username/password execution bypasses the daemon. Saved profiles and SSH config aliases may use the daemon:

```bash
bash <ssh-skill-dir>/scripts/run.sh exec prod -- "hostname"
```

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
- Supports `--username`, `--password`, `--port`, `--connect-timeout`, `--session-timeout`, `--term`, `--rows`, and `--cols`.
- Does not support `--save` or `--save-as`; save profiles with `test --save`.
- Accepts local options only before `--`; everything after `--` is the remote command.
- Writes no final JSON to stdout. Use `--summary-file PATH` for a small JSON result file.
- Records no transcript by default. Use `--log-file PATH` to write raw remote terminal output bytes. Existing logs are refused unless `--append-log` or `--overwrite-log` is passed.

Summary and log paths are resolved under the selected project root. `--summary-file` refuses to overwrite an existing file unless `--overwrite-summary` is passed.

List or remove saved project credentials:

```bash
bash <ssh-skill-dir>/scripts/run.sh credentials list
bash <ssh-skill-dir>/scripts/run.sh credentials remove prod
```

Inspect or stop the daemon for a target:

```bash
bash <ssh-skill-dir>/scripts/run.sh control status <target>
bash <ssh-skill-dir>/scripts/run.sh control stop <target>
```

## Project State

Saved profiles and daemon state live under `.ssh-skill/` in the selected project root.

Saved profiles are plaintext JSON at `.ssh-skill/.credentials.json`. The CLI:

- Creates `.ssh-skill/` with mode `0700`
- Writes `.credentials.json` atomically with mode `0600`
- Rejects symlinked credential files and state directories
- Writes `.ssh-skill/.gitignore` with `/.credentials.json`
- Never returns passwords from list, find, credential listing, daemon status, or errors

Treat saved profiles as local plaintext secrets. Do not print, commit, publish, or copy them.

## SSH Config Metadata

`list` and `find` read optional comments immediately before a `Host` block:

```sshconfig
# description: Production web entrypoint
# environment: production
# tags: web,nginx
# location: us-east
Host prod-web
    HostName 203.0.113.10
    User root
```

These fields only help target discovery. They do not affect connection behavior.

## Boundaries

- Use this CLI instead of raw `ssh`, `scp`, or `sftp` when the skill is available.
- Use `interactive` for commands that require PTY, shell prompts, menus, or interactive sudo.
- Before destructive remote changes, privilege changes, service restarts, data deletion, or broad writes, explain the exact command and expected impact, then get user confirmation.
- Do not create, edit, delete, or manage SSH config entries from this skill.
- Do not use this skill for SSH tunnels, key management, `rsync`, server-to-server copy, or batch host fan-out.
- Do not expose passwords, private keys, saved credential files, or downloaded secrets in chat.
