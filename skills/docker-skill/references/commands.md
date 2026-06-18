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

Prefer Compose commands when the target is managed by Compose. If multiple candidates exist, list them and ask the user to choose before changing state.

### 2. Keep operations bounded

Default to read-only diagnostics and bounded output:

- List containers, services, images, networks, or volumes.
- Read recent logs with a `--tail` limit.
- Inspect structured runtime state.
- Use `docker stats --no-stream` for resource snapshots.

Use state-changing commands only with a clear target and reason. Prefer non-interactive `exec` and one-time commands that return output and exit.

### 3. Confirm risky operations

Ask for explicit confirmation before destructive, broad, publishing, or production-like operations, including container/image/volume deletion, `prune`, `compose down`, `compose down -v`, registry login/push, remote contexts, and migration commands that may change application data unless the user already requested that exact operation.

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

If there are multiple plausible targets, list the candidates and ask the user to choose before changing state. Do not stop, restart, remove, exec into, or run migrations against a guessed target.

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

State-changing operations require a clear target and reason:

- `docker start`, `stop`, `restart`
- `docker compose up`, `stop`, `restart`
- `docker exec`
- `docker compose exec`, `run`
- `docker build`
- `docker compose build`
- `docker cp`

Ask for explicit confirmation before destructive, publishing, or broad operations:

- `docker rm`, `docker rmi`
- `docker volume rm`, `docker network rm`
- `docker compose down`
- `docker compose down -v`
- `docker system prune`, `docker builder prune`, `docker image prune`, `docker volume prune`
- `docker push`, registry login, `buildx build --push`
- Operations against non-local, remote, production, staging, or cloud Docker contexts

## Context Checks

Before state-changing operations, check the active Docker context:

```bash
docker context show
docker context inspect <context>
```

If the context is not clearly local, or its name/metadata suggests `prod`, `production`, `staging`, `remote`, a cloud provider, or a shared host, ask for confirmation before changing state. Read-only commands may be run first, but report the context used.

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

Do not default to `docker compose down`. Prefer `stop` when the goal is only to stop services. Use `down` only when the user wants to tear down the project environment, recreate networks, or clear broken container state. Confirm separately before `down -v` because it removes volumes.

Use profiles and one-time commands only for explicit goals:

```bash
docker compose --profile tools up -d
docker compose run --rm <service> <command>
docker compose up -d --scale <service>=<n>
```

Migration or management commands may change application data. Explain the likely effect and confirm unless the user already explicitly requested that exact operation.

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

Copying out is appropriate for logs, generated artifacts, or config samples. Copying in is temporary debugging, not a durable fix, because containers are replaceable. Confirm paths before copying and avoid overwriting local files. Do not copy suspected secrets, database files, private keys, or large data sets unless the user explicitly asks and accepts the risk.

## Cleanup

It is acceptable to remove temporary containers or Compose projects clearly created during the current task, after explaining the target. If ownership is unclear, ask first.

Prefer:

```bash
docker compose stop
docker stop <container>
```

Confirm before:

```bash
docker rm <container>
docker rmi <image>
docker volume rm <volume>
docker network rm <network>
docker compose down
docker compose down -v
docker system prune
docker builder prune
```

## Reporting

For Docker operations, report:

- Docker context used.
- Target project, service, container, image, volume, or network.
- Commands run and whether they changed state.
- Key findings from logs or inspection, with secrets redacted.
- Cleanup performed or intentionally skipped.
- Commands not run because they required confirmation or were too risky.
