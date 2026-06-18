# Docker Build Recipes

Use these patterns when creating, repairing, or modernizing `Dockerfile`, `.dockerignore`, `compose.yaml`, `compose.yml`, `docker-compose.yaml`, or `docker-compose.yml`. Treat them as starting points, not blind templates. Preserve project-specific commands, ports, and deployment assumptions discovered from the repository.

## Contents

- Universal checks
- Dockerfile defaults
- Node.js
- Python
- Go
- Java
- Static sites
- Databases and caches
- Compose file patterns
- BuildKit and advanced builds
- .dockerignore patterns

## File Workflow

### 1. Inspect the project first

Collect the facts that determine the Docker design before editing files:

- Existing Docker files: `Dockerfile`, `Dockerfile.*`, `.dockerignore`, `compose.yaml`, `compose.yml`, `docker-compose.yaml`, `docker-compose.yml`.
- Runtime docs and entrypoints: `README*`, `Makefile`, `justfile`, `Procfile`, CI workflows, deploy scripts, package scripts, framework config, and existing service managers.
- Language and package manager files: lock files, manifests, workspace files, build config, and test config.
- Runtime needs: application port, start command, build command, static asset output, database/cache/queue dependencies, health endpoint, required environment variables, and persistent data paths.
- Existing conventions: file names, image tags, compose profiles, exposed ports, user IDs, and service names.

Prefer preserving existing intent and public interfaces. For repair tasks, fix the concrete problem first; avoid broad rewrites unless the user asks for modernization or the current design is unsafe or clearly broken.

### 2. Choose file names and scope

- Use the repository's existing Compose file name when one exists.
- For new Compose files, prefer `compose.yaml`; use `docker-compose.yaml` only when requested or when the project already documents that name.
- Do not add a top-level Compose `version` field for new Compose v2 files.
- Create or update `.dockerignore` for nearly every application image.
- Create `.env.example` only when Compose or the image needs environment variables and no suitable example exists.
- Keep Kubernetes, Helm, Swarm, cloud deployment, registry login, image push, and CI release workflows out of scope unless the user explicitly asks for them.

### 3. Build production-capable images by default

Default Dockerfiles should be deployable unless the user asks only for local development:

- Use multi-stage builds where they reduce final image size or isolate build tooling.
- Pin base images to explicit major or minor tags; do not introduce `latest`.
- Copy dependency manifests and lock files before source files to preserve cache.
- Install dependencies with the package manager implied by lock files.
- Run the final application as a non-root user when the base image and framework allow it.
- Keep secrets, `.env` contents, private keys, credentials, and tokens out of Dockerfiles, image layers, Compose files, logs, and final replies.
- Avoid copying `node_modules`, virtualenvs, build caches, test output, `.git`, local databases, and editor state into the build context.

### 4. Use Compose for local integration and dependent services

Default Compose files should make local development and integration validation reliable:

- Separate application services from infrastructure services such as databases, caches, queues, and object stores.
- Use named volumes for stateful services.
- Add healthchecks where there is a clear health endpoint or standard service probe.
- Use `depends_on` with health conditions when startup order matters and the Compose implementation supports it.
- Prefer `env_file: .env` plus `.env.example` placeholders for local configuration; never write real secrets.
- Bind mount source code only for development services, not production-like services.
- Avoid hardcoding host ports when the project already has port conventions; otherwise choose obvious defaults and document them.

### 5. Validate from low risk to higher risk

Detect the Compose command before running Compose operations:

```bash
docker compose version
docker-compose version
```

Prefer `docker compose` when available; fall back to `docker-compose` only when needed. Use the detected Compose command consistently in validation commands.

Validation order:

1. Run syntax/config checks such as `docker compose config`.
2. Build images with `docker build` or `docker compose build`.
3. Start short-lived validation with `docker compose up --build` only when appropriate for the host agent's confirmation and cleanup model.
4. Check health endpoints, container logs, and exit codes when services start.

If validation requires network pulls, long-running services, host port exposure, Docker volume writes, production contexts, or any action the host agent treats as privileged, request confirmation or clearly report that validation was not run.

## Universal Checks

Before writing or changing Docker build files, identify:

- Package manager and lock file.
- Build command, start command, test command, and migration command if present.
- Runtime port and health endpoint.
- Whether the final artifact is source code, a compiled binary, a JAR, static files, or framework-specific output.
- Whether native build tooling is needed only during build or also at runtime.
- Whether the app needs a database, cache, queue, object store, worker, scheduler, or one-time migration task.
- Existing CI/deploy conventions that already define image tags, platforms, or build args.

Prefer explicit image tags such as `node:22-alpine`, `python:3.12-slim`, `golang:1.23-alpine`, `eclipse-temurin:21-jre`, `postgres:16-alpine`, or `redis:7-alpine`. Adjust versions to match the project. Do not introduce `latest`.

## Dockerfile Defaults

Default to production-capable images unless the user asks only for local development:

- Use multi-stage builds where they reduce final image size or isolate build tooling.
- Copy dependency manifests and lock files before source files to preserve cache.
- Install dependencies with the package manager implied by lock files.
- Run the final application as a non-root user when the base image and framework allow it.
- Keep secrets, `.env` contents, private keys, credentials, and tokens out of Dockerfiles and image layers.
- Avoid copying `node_modules`, virtualenvs, build caches, test output, `.git`, local databases, and editor state into the build context.
- Use `HEALTHCHECK` only when the image has a stable local probe command and the project benefits from image-level health.

## Node.js

Detect the package manager from lock files:

- `package-lock.json` or `npm-shrinkwrap.json`: use `npm ci`.
- `pnpm-lock.yaml`: use `corepack enable` and `pnpm install --frozen-lockfile`.
- `yarn.lock`: use `corepack enable` and `yarn install --immutable` for modern Yarn; use `yarn install --frozen-lockfile` for Yarn v1 projects.
- `bun.lock` or `bun.lockb`: use a Bun image only when the project is already Bun-based.

Typical production pattern:

- Stage 1 installs dependencies from manifest and lock files.
- Stage 2 builds the app if `build` exists.
- Final stage copies only runtime files or build output.
- Use `NODE_ENV=production` in the final image.
- Run as the built-in `node` user when possible.

Framework notes:

- Express, Fastify, Nest, and similar servers usually run `node dist/...` or `npm run start:prod`.
- Next.js should use standalone output when configured: set `output: "standalone"` in `next.config.*` if appropriate, then copy `.next/standalone`, `.next/static`, and `public`.
- Vite, React SPA, Vue, SvelteKit static adapters, and other static builds usually belong in an Nginx or other static file server final image unless the project has its own server.

Avoid copying local `node_modules` into the image. Exclude it in `.dockerignore`.

## Python

Detect dependency tooling:

- `requirements.txt`: install with `pip install --no-cache-dir -r requirements.txt`.
- `pyproject.toml` plus `uv.lock`: use `uv sync --frozen` or export/install according to the project convention.
- `poetry.lock`: use Poetry in the build stage or export requirements when that is the project norm.
- `Pipfile.lock`: use Pipenv only when the project already depends on it.

Typical production pattern:

- Use `python:<version>-slim`.
- Install system build packages only in a build stage when wheels or native extensions require them.
- Prefer a virtual environment under `/opt/venv` or direct system install in the image; do not copy a host `.venv`.
- Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`.
- Create a non-root user for the final container.

Framework notes:

- FastAPI and ASGI apps often run with `uvicorn module:app --host 0.0.0.0 --port <port>`.
- Django production containers usually run `gunicorn project.wsgi:application --bind 0.0.0.0:<port>` and need explicit static collection only if the project expects it.
- Flask apps may use `gunicorn module:app` rather than the development server.

Do not bake real `.env` files into images. Use Compose `env_file` or runtime environment injection.

## Go

Typical production pattern:

- Build in `golang:<version>-alpine` or `golang:<version>` depending on CGO needs.
- Copy `go.mod` and `go.sum` first, run `go mod download`, then copy source.
- Build a static binary with `CGO_ENABLED=0` when dependencies allow it.
- Use a minimal final image such as `alpine`, `distroless`, or `scratch` only when certificates, timezone data, shell access, and debugging needs are understood.
- Copy CA certificates into very small final images when the app makes outbound TLS calls.

If CGO is required, keep compatible runtime libraries in the final image.

## Java

Detect build tooling:

- Maven: `mvn package` or `mvn -DskipTests package` according to project practice.
- Gradle: use the checked-in wrapper `./gradlew` when present.

Typical production pattern:

- Build with a JDK image such as `eclipse-temurin:21-jdk`.
- Run with a JRE image such as `eclipse-temurin:21-jre`.
- Copy only the built JAR or distribution output into the final stage.
- Run as a non-root user.

Use the Java version declared by `pom.xml`, `build.gradle*`, `.java-version`, `toolchains.xml`, or CI config.

## Static Sites

For static frontend builds:

- Build with the language-specific builder image.
- Copy final assets from `dist`, `build`, `out`, or the configured output directory.
- Serve with a pinned Nginx, Caddy, or other static server image.
- Add a healthcheck only when the server has a stable local endpoint.

For SPAs, include server fallback configuration when client-side routing requires it.

## Databases and Caches

Use pinned official images unless the project requires custom extensions:

- PostgreSQL: `postgres:<major>-alpine`, named volume for `/var/lib/postgresql/data`, variables for database, user, and password.
- MySQL or MariaDB: named volume for data directory, root and app credentials through variables.
- Redis: `redis:<major>-alpine`, named volume only when persistence is required.
- RabbitMQ, Kafka, Elasticsearch, MinIO, and similar services need explicit ports, volumes, healthchecks, and memory considerations. Add them only when the app actually depends on them.

Never put real passwords in Compose. Use placeholders in `.env.example`.

## Compose File Patterns

Application service checklist:

- `build.context` points at the smallest correct context.
- `dockerfile` is set only when not using the default `Dockerfile`.
- `ports` maps the discovered application port.
- `env_file: .env` is used when local variables are required.
- `environment` contains only non-secret defaults or variable references.
- `depends_on` models infrastructure dependencies.
- `healthcheck` uses a command available inside the container.

Development-only checklist:

- Use bind mounts for source only when the user needs live reload.
- Keep dependency directories inside named volumes when bind mounting would hide installed dependencies.
- Consider Compose `profiles` for optional services such as admin UI, mail catcher, or observability.

Production-like checklist:

- Do not bind mount source.
- Do not expose unnecessary ports.
- Avoid `container_name` unless the project requires stable names.
- Avoid privileged options and broad host mounts.

## BuildKit and Advanced Builds

Use BuildKit features when they solve a concrete build problem:

- Use cache mounts for package manager caches when rebuild speed matters and syntax support is acceptable.
- Use secret mounts for private package tokens or credentials; do not pass secrets through `ARG`, `ENV`, or files copied into the image.
- Use `--target <stage>` to debug or build a specific multi-stage target.
- Use `--build-arg` only for non-secret build-time configuration.
- Use `--platform` only for explicit cross-architecture needs, CI parity, or Apple Silicon/amd64 compatibility issues.
- Treat `docker buildx build --push` and multi-architecture publishing as registry operations that require confirmation.

## .dockerignore Patterns

Common exclusions:

```gitignore
.git
.idea
.vscode
.DS_Store
node_modules
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*
.venv
venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
dist
build
coverage
.env
.env.*
!.env.example
docker-compose.override.yml
compose.override.yml
compose.override.yaml
```

Adjust exclusions to avoid hiding files required by the build. For example, do not ignore `dist` when the Docker build intentionally copies prebuilt assets from `dist`.
