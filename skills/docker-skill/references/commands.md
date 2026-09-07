# Docker Commands

Use this reference when operating Docker, Docker Compose, images, containers, networks, volumes, or running services. Prefer precise, bounded commands that produce inspectable output. Avoid interactive sessions unless the user explicitly requests them and the agent runtime can manage them safely.

## Contents

- Command selection
- Target selection
- Risk tiers
- Context checks
- Read-only diagnostics
- Compose operations
- Container operations
- Exec and one-time commands
- Logs and output limits
- Inspecting runtime state
- Copying files
- Cleanup
- Reporting

## Operations Workflow

### 1. Identify context and target

For any task against a running Docker environment, first identify:

- Active Docker context, especially before state-changing commands.
- Whether the target is Compose-managed or a standalone container.
- Target project directory, Compose file, service, container ID/name, image, network, or volume.
- Whether multiple plausible targets exist.

Prefer Compose commands when the target is managed by Compose. Resolve the target using the order in Target Selection below.

### 2. Keep operations bounded

Default to read-only diagnostics and bounded output:

- List containers, services, images, networks, or volumes.
- Read recent logs with a `--tail` limit.
- Inspect structured runtime state.
- Use `docker stats --no-stream` for resource snapshots.

Use state-changing commands only with a clear target and reason. Prefer non-interactive `exec` and one-time commands that return output and exit.

### 3. Apply authorization boundaries

Use [Authorization and Completion](../SKILL.md#authorization-and-completion) for approval requirements, existing authorization, temporary cleanup, and blocked work. The command lists below describe effects, not additional confirmation gates.

## Command Selection

Detect Compose support before using Compose:

```bash
docker compose version
docker-compose version
```

Prefer `docker compose` when available. Fall back to `docker-compose` only when the plugin form is unavailable. Use the selected command consistently in a task.

Prefer Compose operations when a project or service is managed by Compose:

- Use `docker compose ps`, `logs`, `exec`, `restart`, `stop`, `up`, and `run` when the Compose project and service are known.
- Use direct `docker` commands when the user gives a container ID/name, the container is not Compose-managed, or the task is daemon-wide.
- For Compose-managed containers, inspect labels such as `com.docker.compose.project`, `com.docker.compose.service`, and `com.docker.compose.config-hash` before falling back to bare container operations.

## Target Selection

Resolve the operation target in this order:

1. User-specified project directory, Compose file, service name, container ID, or container name.
2. Compose files in the current working directory.
3. Compose labels on the relevant running container.
4. A candidate selected from `docker ps` or `docker compose ps`.

If multiple plausible targets remain after checking the request, project files, and labels, list them and ask the user to choose before operating on one. Do not guess a target merely because it appears first in a listing.

When the Compose file is known, prefer an explicit file argument such as:

```bash
docker compose -f compose.yaml ps
```

## Risk Tiers

Default allowed read-only or low-risk diagnostics:

- `docker ps`
- `docker images`
- `docker logs --tail <n>`
- `docker inspect`
- `docker stats --no-stream`
- `docker top`
- `docker port`
- `docker network inspect`
- `docker volume inspect`
- `docker compose ps`
- `docker compose logs --tail <n>`
- `docker compose config`

Operations that can change state require a clear target and a purpose within the request. Classify `exec` by the command it runs:

- `docker start`, `stop`, `restart`
- `docker compose up`, `stop`, `restart`
- `docker exec`
- `docker compose exec`, `run`
- `docker build`
- `docker compose build`
- `docker cp`

For destructive, publishing, privileged, or non-local operations, apply the authorization rules linked above, including their existing-approval and temporary-cleanup exceptions.

## Context Checks

Before state-changing operations, check the active Docker context:

```bash
docker context show
docker context inspect <context>
```

Use the endpoint and metadata to establish whether the context is local, remote, or shared; names such as `prod`, `staging`, or `remote` are clues to investigate. Apply the authorization rules before changing state and report the context used. Read-only inspection does not require a separate context approval.

## Read-Only Diagnostics

Start with bounded inspection:

```bash
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'
docker compose ps
docker images
docker stats --no-stream
```

For a failing service, gather:

- Container status and exit code.
- Recent logs.
- Health status.
- Ports and bindings.
- Mounts and volume status.
- Restart policy.
- Image tag and creation time.

## Compose Operations

Use Compose for project-level lifecycle:

```bash
docker compose config
docker compose ps
docker compose logs --tail 200 <service>
docker compose up -d <service>
docker compose restart <service>
docker compose stop <service>
```

Do not default to `docker compose down`. Prefer `stop` when the goal is only to stop services. Use `down` for authorized teardown or qualifying temporary cleanup. Volume deletion with `down -v` must be explicitly included in the authorization.

Use profiles and one-time commands only for explicit goals:

```bash
docker compose --profile tools up -d
docker compose run --rm <service> <command>
docker compose up -d --scale <service>=<n>
```

For migration or management commands that change application data, identify the affected data and apply the authorization rules before execution.

## Container Operations

Use direct container lifecycle commands for non-Compose containers or explicitly named targets:

```bash
docker start <container>
docker stop <container>
docker restart <container>
```

Prefer container IDs or exact names from `docker ps`. Avoid substring matching for state-changing commands.

## Exec and One-Time Commands

Prefer non-interactive, bounded commands:

```bash
docker exec <container> sh -lc '<command>'
docker compose exec -T <service> sh -lc '<command>'
docker compose run --rm <service> <command>
```

If `sh` is unavailable, try the shell or entrypoint tools the image actually provides, or execute the target binary directly. Do not open an interactive shell, TTY, editor, pager, or menu-driven program by default.

Use `docker compose exec -T` for automation so the command does not require a TTY.

## Logs and Output Limits

Limit logs by default:

```bash
docker logs --tail 200 <container>
docker compose logs --tail 200 <service>
```

Use `--tail 300` for startup failures when useful. Do not use `-f` by default; only follow logs for a short, interruptible observation window when the agent runtime supports it. Avoid dumping complete logs unless the user asks or the log is known to be small.

## Inspecting Runtime State

Use `docker inspect` for structured facts:

```bash
docker inspect <container>
docker inspect --format '{{json .State.Health}}' <container>
docker inspect --format '{{json .Config.Env}}' <container>
docker inspect --format '{{json .NetworkSettings.Ports}}' <container>
docker inspect --format '{{json .Mounts}}' <container>
docker inspect --format '{{json .HostConfig.RestartPolicy}}' <container>
```

Useful adjunct commands:

```bash
docker top <container>
docker port <container>
docker stats --no-stream <container>
docker network inspect <network>
docker volume inspect <volume>
```

Environment variables may contain secrets. Summarize variable names and suspicious missing or malformed entries; do not paste secret values into the final response.

## Copying Files

Use `docker cp` for explicit, bounded file transfer:

```bash
docker cp <container>:/path/in/container ./local-path
docker cp ./local-path <container>:/path/in/container
```

Copying out is appropriate for logs, generated artifacts, or config samples. Copying in is temporary debugging, not a durable fix, because containers are replaceable. Verify source and destination paths through inspection; ask only if the destination or overwrite intent is unresolved. Avoid overwriting local files. Do not copy suspected secrets, database files, private keys, or large data sets unless the user explicitly asks and accepts the risk.

## Cleanup

Check ownership and data-retention needs, then apply the temporary-cleanup exception in [Authorization and Completion](../SKILL.md#authorization-and-completion). Stop services when the task only calls for stopping them:

```bash
docker compose stop
docker stop <container>
```

For qualifying temporary cleanup, target exact container/network IDs or the task-specific Compose project. Do not use broad prune commands as a shortcut. Report retained resources and any cleanup still awaiting approval.

## Reporting

For Docker operations, report:

- Docker context used.
- Target project, service, container, image, volume, or network.
- Commands run and whether they changed state.
- Key findings from logs or inspection, with secrets redacted.
- Cleanup performed or intentionally skipped.
- Commands not run because they required confirmation or were too risky.
