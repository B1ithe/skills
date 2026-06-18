---
name: docker-skill
description: Operate Docker and Docker Compose projects safely, including creating, reviewing, repairing, and validating Dockerfiles, .dockerignore files, and Compose configurations; inspecting and debugging running containers; viewing logs; executing non-interactive commands in containers; managing Compose services; building, starting, stopping, and restarting services; inspecting images, networks, and volumes; copying bounded files; and troubleshooting Docker runtime issues. Use when an agent needs Docker or Docker Compose file work, command execution, local container operations, build/runtime debugging, image or service inspection, or safe Docker cleanup.
---

# Docker Skill

## Overview

Use Docker and Docker Compose as a practical project workflow: inspect how the project or Docker daemon is currently shaped, create or repair the smallest correct container configuration when files need work, operate running containers and Compose services when requested, validate with Docker commands when possible, and report exactly what changed or was observed.

This skill is written for general agents. Do not assume Codex-specific tools, UI, sandbox behavior, or approval mechanics. Use the host agent's normal file editing, command execution, and confirmation flow.

## Reference Routing

Load only the reference needed for the current request:

- For creating, repairing, modernizing, or validating `Dockerfile`, `.dockerignore`, `compose.yaml`, `compose.yml`, `docker-compose.yaml`, or `docker-compose.yml`, read [references/build-recipes.md](references/build-recipes.md).
- For operating Docker or Docker Compose, inspecting running containers, reading logs, executing commands in containers, copying files, restarting services, checking images/networks/volumes, or cleanup, read [references/commands.md](references/commands.md).
- For tasks that combine file changes and runtime validation, read both references as needed.

## Safety Baseline

Apply these rules before loading deeper references:

- Treat Docker commands as host-affecting operations. Identify the Docker context and target before changing state.
- Prefer Compose commands when the target is Compose-managed.
- Prefer read-only diagnostics and bounded output before state-changing commands.
- Keep secrets, `.env` contents, private keys, credentials, and tokens out of Dockerfiles, image layers, Compose files, logs, and final replies.
- Do not add or preserve high-risk container privileges by default: `privileged: true`, `network_mode: host`, broad host mounts, `/var/run/docker.sock` mounts, broad `cap_add`, or long-running root processes.
- Ask for explicit confirmation before destructive, broad, publishing, or production-like operations such as `docker push`, registry login, `docker system prune`, deleting volumes, `compose down -v`, restarting production services, or operating against a remote/production Docker context.

## Reporting

Final output should state:

- Files created or modified.
- Docker context used.
- Target project, service, container, image, network, or volume.
- Important assumptions about runtime command, ports, environment variables, and dependent services.
- Commands run, whether they passed, and whether they changed state.
- Key findings from logs or inspection, with secrets redacted.
- Cleanup performed or intentionally skipped.
- Commands not run and the reason.

## Resources

### references/

- `build-recipes.md`: Dockerfile, Compose file, BuildKit, stack-specific image, dependency service, and `.dockerignore` patterns. Load it when creating or repairing Docker project files.
- `commands.md`: Docker and Compose command workflows for running containers, logs, exec, lifecycle operations, inspection, file copy, context checks, cleanup, and runtime troubleshooting. Load it when operating Docker or a running Compose project.
