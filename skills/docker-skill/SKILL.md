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

## Authorization and Completion

This section is the approval source of truth for both references. Host execution permissions still apply.

- Resolve targets from the request, project files, and container labels before asking. Ask if the required target is still missing or ambiguous; bounded read-only diagnostics may proceed on the requested environment, including remote contexts.
- Perform necessary local builds and short-lived validation within the requested scope. Image pulls, task-specific test volumes, and loopback-bound test ports do not by themselves require another confirmation. Inspect mounts first; isolate validation from existing application data and stop temporary services after checking health, logs, and exit codes.
- Require explicit authorization for container/network deletion, deleting any images or volumes, `compose down`, prune operations, registry login/push (including `buildx --push`), data-changing migrations, privileged operations, and state changes in remote, shared, staging, production, or cloud contexts. If the context is not clearly local, resolve it or obtain authorization before changing state.
- An explicit request or prior approval covering the same target, operation, and effects satisfies that requirement. Reuse it; ask again only for a material change in scope or impact. Approval to stop services or run `down` does not authorize volume deletion with `down -v`.
- Cleanup exception: after identifying the targets, remove temporary local containers and networks created solely for this task when they contain no data to retain. A task-specific local Compose project may be removed with `down` without `-v` after checking that all affected containers and networks meet this exception. Pre-existing resources, images, volumes, remote changes, and broad prune operations remain subject to the rule above.
- When approval is missing, finish read-only diagnosis, authorized local file changes, and concrete command/impact preparation first. Pause only the dependent operation. If execution is blocked, complete other available checks and report the exact unverified behavior or unfinished operation; do not mark the whole task complete merely because a configuration file was written.

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
