#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.util
import json
import os
import posixpath
import select
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


IDLE_TIMEOUT_SECONDS = 1800
HEARTBEAT_SECONDS = 60
MAX_MESSAGE_BYTES = 10 * 1024 * 1024
BUFFER_SIZE = 65536
CREDENTIALS_SCHEMA_VERSION = 1
CREDENTIALS_FILE_NAME = ".credentials.json"
CREDENTIALS_GITIGNORE_ENTRY = f"/{CREDENTIALS_FILE_NAME}"


class SSHSkillError(Exception):
    pass


class DependencyError(SSHSkillError):
    pass


@dataclass
class HostEntry:
    alias: str
    hostname: str = ""
    user: str = ""
    port: int = 22
    identity_file: str | None = None
    proxy_jump: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        auth = "key" if self.identity_file else "agent-or-default"
        return {
            "alias": self.alias,
            "hostname": self.hostname,
            "user": self.user,
            "port": self.port,
            "identity_file": self.identity_file,
            "proxy_jump": self.proxy_jump,
            "auth": auth,
            "metadata": {
                "description": self.metadata.get("description", ""),
                "environment": self.metadata.get("environment", ""),
                "tags": self.metadata.get("tags", []),
                "location": self.metadata.get("location", ""),
            },
            "source": "ssh-config",
        }


@dataclass
class ProjectProfile:
    name: str
    hostname: str
    username: str
    password: str = field(repr=False)
    port: int = 22

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alias": self.name,
            "hostname": self.hostname,
            "user": self.username,
            "username": self.username,
            "port": self.port,
            "identity_file": None,
            "proxy_jump": None,
            "auth": "password",
            "metadata": {
                "description": "",
                "environment": "",
                "tags": [],
                "location": "",
            },
            "source": "project-credentials",
        }


@dataclass
class ConnectionConfig:
    target: str
    hostname: str
    username: str | None = None
    port: int = 22
    password: str | None = field(default=None, repr=False)
    identity_file: str | None = None
    proxy_jump: str | None = None
    source: str = "direct"


@dataclass
class ConnectionOptions:
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    password_stdin: bool = False
    port: int | None = None
    save: bool = False
    save_as: str | None = None

    def has_explicit_connection_values(self) -> bool:
        return any(
            (
                self.username is not None,
                self.password is not None,
                self.port is not None,
            )
        )


def script_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_config_path() -> Path:
    return Path.home() / ".ssh" / "config"


def ssh_skill_state_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / ".ssh-skill"


def credentials_path(root: Path | None = None) -> Path:
    return ssh_skill_state_dir(root) / CREDENTIALS_FILE_NAME


def paramiko_available() -> bool:
    return importlib.util.find_spec("paramiko") is not None


def ensure_paramiko():
    if not paramiko_available():
        skill_dir = script_root()
        launcher_path = skill_dir / "scripts" / "run.sh"
        command = (
            f"bash {shlex.quote(str(launcher_path))} <command> ..."
        )
        raise DependencyError(
            f"Missing required Python package: paramiko in {sys.executable}. "
            f"Run this skill through its launcher: {command} "
            "When uv is unavailable, install Paramiko into the selected Python 3.11+ "
            "environment outside the skill runtime, then retry."
        )
    import paramiko  # type: ignore

    return paramiko


def json_print(payload: dict[str, Any], *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


def json_error(message: str, *, exit_code: int = 1, detail: str | None = None) -> int:
    payload: dict[str, Any] = {"success": False, "error": message}
    if detail:
        payload["detail"] = detail
    json_print(payload)
    return exit_code


def validate_port(port: int) -> int:
    if not 1 <= port <= 65535:
        raise SSHSkillError("SSH port must be between 1 and 65535")
    return port


def validate_profile_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise SSHSkillError("Credential profile name must not be empty")
    if any(ord(character) < 32 for character in normalized):
        raise SSHSkillError("Credential profile name must not contain control characters")
    return normalized


def _check_credentials_file_security(path: Path) -> None:
    if path.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked credentials file: {path}")
    if not path.exists() or os.name == "nt":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SSHSkillError(
            f"Credentials file permissions are too broad: {path} has mode {mode:04o}; expected 0600"
        )


def _ensure_credentials_directory(root: Path) -> Path:
    directory = ssh_skill_state_dir(root)
    if directory.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked SSH skill state directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


def load_project_profiles(root: Path | None = None) -> dict[str, ProjectProfile]:
    project_root = root or Path.cwd()
    path = credentials_path(project_root)
    if not path.exists() and not path.is_symlink():
        return {}
    _check_credentials_file_security(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SSHSkillError(f"Unable to read project SSH credentials: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CREDENTIALS_SCHEMA_VERSION:
        raise SSHSkillError(
            f"Unsupported project SSH credentials schema in {path}; expected schema_version "
            f"{CREDENTIALS_SCHEMA_VERSION}"
        )
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict):
        raise SSHSkillError(f"Invalid project SSH credentials profiles in {path}")

    profiles: dict[str, ProjectProfile] = {}
    for raw_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_name, str) or not isinstance(raw_profile, dict):
            raise SSHSkillError(f"Invalid project SSH credential profile in {path}")
        name = validate_profile_name(raw_name)
        hostname = raw_profile.get("hostname")
        username = raw_profile.get("username")
        password = raw_profile.get("password")
        port = raw_profile.get("port", 22)
        if not isinstance(hostname, str) or not hostname.strip():
            raise SSHSkillError(f"Credential profile {name!r} has an invalid hostname")
        if not isinstance(username, str) or not username.strip():
            raise SSHSkillError(f"Credential profile {name!r} has an invalid username")
        if not isinstance(password, str) or not password:
            raise SSHSkillError(f"Credential profile {name!r} has an invalid password")
        if not isinstance(port, int) or isinstance(port, bool):
            raise SSHSkillError(f"Credential profile {name!r} has an invalid port")
        profiles[name] = ProjectProfile(
            name=name,
            hostname=hostname.strip(),
            username=username.strip(),
            password=password,
            port=validate_port(port),
        )
    return profiles


def _write_credentials_gitignore(directory: Path) -> None:
    path = directory / ".gitignore"
    if path.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked SSH skill gitignore: {path}")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    if CREDENTIALS_GITIGNORE_ENTRY in lines:
        return
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(f"{prefix}{CREDENTIALS_GITIGNORE_ENTRY}\n", encoding="utf-8")


def write_project_profiles(profiles: dict[str, ProjectProfile], root: Path | None = None) -> None:
    project_root = root or Path.cwd()
    directory = _ensure_credentials_directory(project_root)
    path = credentials_path(project_root)
    if path.exists() or path.is_symlink():
        _check_credentials_file_security(path)
    _write_credentials_gitignore(directory)
    payload = {
        "schema_version": CREDENTIALS_SCHEMA_VERSION,
        "profiles": {
            name: {
                "hostname": profile.hostname,
                "port": profile.port,
                "username": profile.username,
                "password": profile.password,
            }
            for name, profile in sorted(profiles.items())
        },
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{CREDENTIALS_FILE_NAME}.",
        suffix=".tmp",
        dir=directory,
    )
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def save_project_profile(
    name: str,
    connection: ConnectionConfig,
    *,
    root: Path,
) -> ProjectProfile:
    profile_name = validate_profile_name(name)
    if not connection.username:
        raise SSHSkillError("Saving SSH credentials requires a username")
    if not connection.password:
        raise SSHSkillError("Saving SSH credentials requires a password")
    profile = ProjectProfile(
        name=profile_name,
        hostname=connection.hostname,
        username=connection.username,
        password=connection.password,
        port=connection.port,
    )
    profiles = load_project_profiles(root)
    profiles[profile_name] = profile
    daemon_stop(profile_name, root=root)
    write_project_profiles(profiles, root)
    return profile


def remove_project_profile(name: str, *, root: Path) -> dict[str, Any]:
    profile_name = validate_profile_name(name)
    profiles = load_project_profiles(root)
    if profile_name not in profiles:
        return {"success": False, "removed": False, "name": profile_name}
    daemon_stop(profile_name, root=root)
    del profiles[profile_name]
    write_project_profiles(profiles, root)
    return {"success": True, "removed": True, "name": profile_name}


def parse_metadata(comment_lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "description": "",
        "environment": "",
        "tags": [],
        "location": "",
    }
    for raw_line in comment_lines:
        line = raw_line.strip()
        if not line.startswith("#"):
            continue
        line = line[1:].strip()
        if not line or line.startswith("=====") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "tags":
            metadata["tags"] = [item.strip() for item in value.split(",") if item.strip()]
        elif key in {"description", "environment", "location"}:
            metadata[key] = value
    return metadata


def _host_aliases(value: str) -> list[str]:
    aliases = shlex.split(value, comments=True, posix=True)
    return [
        alias
        for alias in aliases
        if "*" not in alias and "?" not in alias and not alias.startswith("!")
    ]


def load_hosts_from_config(config_path: Path | None = None) -> list[HostEntry]:
    path = config_path or default_config_path()
    if not path.exists():
        return []

    hosts: list[HostEntry] = []
    current_aliases: list[str] = []
    current_options: dict[str, str] = {}
    current_metadata: dict[str, Any] = {}
    pending_comments: list[str] = []

    def flush_current() -> None:
        if not current_aliases:
            return
        for alias in current_aliases:
            hosts.append(
                HostEntry(
                    alias=alias,
                    hostname=current_options.get("hostname", alias),
                    user=current_options.get("user", ""),
                    port=_parse_port(current_options.get("port")),
                    identity_file=current_options.get("identityfile"),
                    proxy_jump=current_options.get("proxyjump"),
                    metadata=dict(current_metadata),
                )
            )

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                pending_comments.append(raw_line)
                continue
            parts = stripped.split(None, 1)
            if not parts:
                continue
            key = parts[0].lower()
            value = parts[1].strip() if len(parts) > 1 else ""
            if key == "host":
                flush_current()
                current_aliases = _host_aliases(value)
                current_options = {}
                current_metadata = parse_metadata(pending_comments)
                pending_comments = []
                continue
            if current_aliases:
                current_options[key] = value
            else:
                pending_comments = []
            pending_comments = []

    flush_current()
    return hosts


def _parse_port(value: str | None) -> int:
    if not value:
        return 22
    try:
        return int(value)
    except ValueError:
        return 22


def find_host(alias: str, config_path: Path | None = None) -> HostEntry:
    for host in load_hosts_from_config(config_path):
        if host.alias == alias:
            return host
    raise SSHSkillError(f"SSH alias not found in {config_path or default_config_path()}: {alias}")


def find_hosts(keyword: str, config_path: Path | None = None) -> list[HostEntry]:
    needle = keyword.lower()
    matches: list[HostEntry] = []
    for host in load_hosts_from_config(config_path):
        haystack = [
            host.alias,
            host.hostname,
            host.user,
            host.metadata.get("description", ""),
            host.metadata.get("environment", ""),
            host.metadata.get("location", ""),
            " ".join(host.metadata.get("tags", [])),
        ]
        if any(needle in str(value).lower() for value in haystack):
            matches.append(host)
    return matches


def list_targets(*, config_path: Path, root: Path) -> list[dict[str, Any]]:
    profiles = load_project_profiles(root)
    targets = [profile.as_dict() for profile in profiles.values()]
    targets.extend(
        host.as_dict()
        for host in load_hosts_from_config(config_path)
        if host.alias not in profiles
    )
    return sorted(targets, key=lambda item: str(item["alias"]).lower())


def find_targets(keyword: str, *, config_path: Path, root: Path) -> list[dict[str, Any]]:
    needle = keyword.lower()
    matches: list[dict[str, Any]] = []
    for target in list_targets(config_path=config_path, root=root):
        metadata = target.get("metadata", {})
        haystack = [
            target.get("alias", ""),
            target.get("hostname", ""),
            target.get("user", ""),
            metadata.get("description", ""),
            metadata.get("environment", ""),
            metadata.get("location", ""),
            " ".join(metadata.get("tags", [])),
        ]
        if any(needle in str(value).lower() for value in haystack):
            matches.append(target)
    return matches


def prepare_connection_options(options: ConnectionOptions) -> ConnectionOptions:
    if options.password_stdin:
        raise SSHSkillError(
            "--password-stdin has been removed; use --password or a saved profile"
        )
    if options.save_as is not None and not options.save:
        raise SSHSkillError("--save-as requires --save")
    password = options.password
    if password == "":
        raise SSHSkillError("--password requires a non-empty password")
    if options.port is not None:
        validate_port(options.port)
    return ConnectionOptions(
        username=options.username,
        password=password,
        password_stdin=options.password_stdin,
        port=options.port,
        save=options.save,
        save_as=options.save_as,
    )


def resolve_connection(
    target: str,
    *,
    config_path: Path,
    root: Path,
    options: ConnectionOptions | None = None,
) -> ConnectionConfig:
    if not target.strip():
        raise SSHSkillError("SSH target must not be empty")
    overrides = options or ConnectionOptions()
    profiles = load_project_profiles(root)
    if target in profiles:
        profile = profiles[target]
        connection = ConnectionConfig(
            target=target,
            hostname=profile.hostname,
            username=profile.username,
            port=profile.port,
            password=profile.password,
            source="project-credentials",
        )
    else:
        config_host = next(
            (host for host in load_hosts_from_config(config_path) if host.alias == target),
            None,
        )
        if config_host:
            connection = ConnectionConfig(
                target=target,
                hostname=config_host.hostname or target,
                username=config_host.user or None,
                port=config_host.port,
                identity_file=config_host.identity_file,
                proxy_jump=config_host.proxy_jump,
                source="ssh-config",
            )
        else:
            connection = ConnectionConfig(
                target=target,
                hostname=target,
                source="direct",
            )

    if overrides.username is not None:
        username = overrides.username.strip()
        if not username:
            raise SSHSkillError("--username requires a non-empty value")
        connection.username = username
    if overrides.password is not None:
        connection.password = overrides.password
    if overrides.port is not None:
        connection.port = validate_port(overrides.port)
    if connection.password and not connection.username:
        raise SSHSkillError(
            "Password authentication requires a username via --username or configuration"
        )
    if overrides.save:
        if not connection.username:
            raise SSHSkillError("Saving SSH credentials requires a username")
        if not connection.password:
            raise SSHSkillError("Saving SSH credentials requires a password")
        validate_profile_name(overrides.save_as or target)
    return connection


def daemon_state_dir(root: Path | None = None) -> Path:
    return ssh_skill_state_dir(root) / "daemon"


def daemon_id(alias: str) -> str:
    return hashlib.md5(alias.lower().encode("utf-8")).hexdigest()[:12]


def daemon_info_path(alias: str, root: Path | None = None) -> Path:
    return daemon_state_dir(root) / f"{daemon_id(alias)}.json"


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_daemon_info(alias: str, root: Path | None = None) -> dict[str, Any] | None:
    path = daemon_info_path(alias, root)
    if not path.exists():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        path.unlink(missing_ok=True)
        return None
    pid = info.get("pid")
    if isinstance(pid, int) and is_process_alive(pid):
        return info
    path.unlink(missing_ok=True)
    return None


def write_daemon_info(alias: str, info: dict[str, Any], root: Path | None = None) -> None:
    directory = daemon_state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    daemon_info_path(alias, root).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def send_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)


def recv_message(sock: socket.socket, timeout: float | None = None) -> dict[str, Any]:
    if timeout is not None:
        sock.settimeout(timeout)
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("Connection closed while reading message header")
        header += chunk
    length = struct.unpack("!I", header)[0]
    if length > MAX_MESSAGE_BYTES:
        raise ValueError(f"Message too large: {length} bytes")
    body = b""
    while len(body) < length:
        chunk = sock.recv(min(BUFFER_SIZE, length - len(body)))
        if not chunk:
            raise ConnectionError("Connection closed while reading message body")
        body += chunk
    return json.loads(body.decode("utf-8"))


def build_proxy_command(paramiko: Any, connection: ConnectionConfig, config_path: Path) -> Any:
    if not connection.proxy_jump:
        return None
    hostname = connection.hostname or connection.target
    port = connection.port or 22
    proxy_jump = connection.proxy_jump
    if "," in proxy_jump:
        jumps = [item.strip() for item in proxy_jump.split(",") if item.strip()]
        command = f"ssh -F {shlex.quote(str(config_path))} -J {shlex.quote(','.join(jumps[:-1]))} -W {shlex.quote(hostname)}:{port} {shlex.quote(jumps[-1])}"
    else:
        command = f"ssh -F {shlex.quote(str(config_path))} -W {shlex.quote(hostname)}:{port} {shlex.quote(proxy_jump)}"
    return paramiko.ProxyCommand(command)


def connect_client(connection: ConnectionConfig, *, config_path: Path, timeout: int):
    paramiko = ensure_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict[str, Any] = {
        "hostname": connection.hostname,
        "port": connection.port,
        "username": connection.username,
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
        "allow_agent": connection.password is None,
        "look_for_keys": connection.password is None,
    }
    if connection.identity_file and connection.password is None:
        connect_kwargs["key_filename"] = os.path.expanduser(connection.identity_file)
    if connection.password is not None:
        connect_kwargs["password"] = connection.password
    proxy = build_proxy_command(paramiko, connection, config_path)
    if proxy is not None:
        connect_kwargs["sock"] = proxy
    client.connect(**connect_kwargs)
    return client


def connect_target(
    target: str,
    *,
    config_path: Path,
    root: Path,
    timeout: int,
) -> tuple[ConnectionConfig, Any]:
    connection = resolve_connection(
        target,
        config_path=config_path,
        root=root,
    )
    return connection, connect_client(connection, config_path=config_path, timeout=timeout)


def close_ssh_client(client: Any) -> None:
    transport = None
    try:
        transport = client.get_transport()
    except Exception:
        transport = None
    try:
        client.close()
    finally:
        if transport and hasattr(transport, "join") and transport is not threading.current_thread():
            try:
                transport.join(timeout=2)
            except Exception:
                pass


def execute_direct(
    connection: ConnectionConfig,
    command: str,
    *,
    config_path: Path,
    timeout: int,
    root: Path,
    save_name: str | None = None,
) -> dict[str, Any]:
    client = connect_client(connection, config_path=config_path, timeout=timeout)
    try:
        if save_name:
            save_project_profile(save_name, connection, root=root)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return {
            "success": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "method": "direct",
        }
    finally:
        close_ssh_client(client)


def try_daemon_execute(alias: str, command: str, *, root: Path, timeout: int) -> dict[str, Any] | None:
    info = read_daemon_info(alias, root)
    if not info:
        return None
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as sock:
            send_message(sock, {"action": "execute", "command": command, "timeout": timeout})
            result = recv_message(sock, timeout=timeout + 5)
            result["method"] = "daemon"
            return result
    except Exception:
        return None


def start_daemon_background(target: str, *, config_path: Path, root: Path, idle_timeout: int) -> bool:
    script = Path(__file__).resolve()
    cmd = [
        sys.executable,
        str(script),
        "--config",
        str(config_path),
        "--root",
        str(root),
        "daemon",
        "start",
        target,
        "--idle-timeout",
        str(idle_timeout),
    ]
    with open(os.devnull, "wb") as devnull:
        subprocess.Popen(cmd, stdout=devnull, stderr=devnull, start_new_session=(os.name != "nt"))
    for _ in range(20):
        time.sleep(0.2)
        if read_daemon_info(target, root):
            return True
    return False


class SSHDaemon:
    def __init__(self, target: str, *, config_path: Path, root: Path, idle_timeout: int):
        self.target = target
        self.alias = target
        self.config_path = config_path
        self.root = root
        self.idle_timeout = idle_timeout
        self.last_activity = time.time()
        self.started_at = time.time()
        self.running = False
        self.server_socket: socket.socket | None = None
        self.ssh_client = None
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.client_sockets: set[socket.socket] = set()
        self.client_sockets_lock = threading.Lock()

    def start(self) -> None:
        if read_daemon_info(self.target, self.root):
            return
        atexit.register(self.shutdown)
        _connection, self.ssh_client = connect_target(
            self.target,
            config_path=self.config_path,
            root=self.root,
            timeout=30,
        )
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(5)
        self.server_socket.settimeout(5.0)
        port = self.server_socket.getsockname()[1]
        self.running = True
        write_daemon_info(
            self.target,
            {
                "pid": os.getpid(),
                "port": port,
                "alias": self.target,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "idle_timeout": self.idle_timeout,
            },
            self.root,
        )
        self._start_thread(self._heartbeat_loop, "ssh-skill-heartbeat")
        self._start_thread(self._idle_loop, "ssh-skill-idle")
        try:
            while self.running:
                try:
                    client_sock, _addr = self.server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._start_thread(self._handle_client, "ssh-skill-client", client_sock)
        finally:
            self.shutdown()

    def _start_thread(self, target: Any, name: str, *args: Any) -> None:
        thread = threading.Thread(target=target, name=name, args=args)
        thread.start()
        self.threads.append(thread)

    def _handle_client(self, client_sock: socket.socket) -> None:
        with self.client_sockets_lock:
            self.client_sockets.add(client_sock)
        try:
            request = recv_message(client_sock, timeout=300)
            action = request.get("action")
            if action == "ping":
                send_message(client_sock, self.status_payload())
                return
            if action == "shutdown":
                send_message(client_sock, {"status": "shutting_down"})
                self.request_stop()
                return
            if action == "execute":
                self.last_activity = time.time()
                command = str(request.get("command", ""))
                timeout = int(request.get("timeout", 30))
                send_message(client_sock, self.execute(command, timeout))
                return
            send_message(client_sock, {"success": False, "exit_code": -1, "stdout": "", "stderr": f"Unknown action: {action}"})
        except Exception as exc:
            try:
                send_message(client_sock, {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)})
            except Exception:
                pass
        finally:
            with self.client_sockets_lock:
                self.client_sockets.discard(client_sock)
            try:
                client_sock.close()
            except Exception:
                pass

    def status_payload(self) -> dict[str, Any]:
        return {
            "status": "running",
            "pid": os.getpid(),
            "alias": self.target,
            "ssh_alive": self.is_ssh_alive(),
            "uptime_seconds": int(time.time() - self.started_at),
            "idle_seconds": int(time.time() - self.last_activity),
        }

    def execute(self, command: str, timeout: int) -> dict[str, Any]:
        with self.lock:
            if not self._is_ssh_alive_unlocked(send_probe=False):
                try:
                    if self.ssh_client:
                        close_ssh_client(self.ssh_client)
                    _connection, self.ssh_client = connect_target(
                        self.target,
                        config_path=self.config_path,
                        root=self.root,
                        timeout=timeout,
                    )
                except Exception as exc:
                    return {"success": False, "exit_code": -1, "stdout": "", "stderr": f"Reconnect failed: {exc}"}
            try:
                stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
                stdout_text = stdout.read().decode("utf-8", errors="replace")
                stderr_text = stderr.read().decode("utf-8", errors="replace")
                exit_code = stdout.channel.recv_exit_status()
                return {
                    "success": exit_code == 0,
                    "exit_code": exit_code,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                }
            except Exception as exc:
                return {"success": False, "exit_code": -1, "stdout": "", "stderr": f"Execution failed: {exc}"}

    def is_ssh_alive(self) -> bool:
        with self.lock:
            return self._is_ssh_alive_unlocked(send_probe=True)

    def _is_ssh_alive_unlocked(self, *, send_probe: bool) -> bool:
        try:
            if not self.ssh_client:
                return False
            transport = self.ssh_client.get_transport()
            if not transport or not transport.is_active():
                return False
            if send_probe:
                transport.send_ignore()
            return True
        except Exception:
            return False

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            if not self.running:
                break
            with self.lock:
                if self._is_ssh_alive_unlocked(send_probe=True):
                    continue
                try:
                    if self.ssh_client:
                        close_ssh_client(self.ssh_client)
                    _connection, self.ssh_client = connect_target(
                        self.target,
                        config_path=self.config_path,
                        root=self.root,
                        timeout=30,
                    )
                except Exception:
                    pass

    def _idle_loop(self) -> None:
        while not self.stop_event.wait(10):
            if time.time() - self.last_activity >= self.idle_timeout:
                self.request_stop()
                return

    def request_stop(self) -> None:
        self.running = False
        self.stop_event.set()
        self._wake_accept()

    def _wake_accept(self) -> None:
        if not self.server_socket:
            return
        try:
            with socket.create_connection(("127.0.0.1", self.server_socket.getsockname()[1]), timeout=1):
                pass
        except Exception:
            pass

    def shutdown(self) -> None:
        self.running = False
        self.stop_event.set()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        with self.client_sockets_lock:
            client_sockets = list(self.client_sockets)
        for client_sock in client_sockets:
            try:
                client_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client_sock.close()
            except Exception:
                pass
        with self.lock:
            if self.ssh_client:
                close_ssh_client(self.ssh_client)
                self.ssh_client = None
        current = threading.current_thread()
        for thread in list(self.threads):
            if thread is current:
                continue
            thread.join(timeout=2)
        daemon_info_path(self.target, self.root).unlink(missing_ok=True)


def daemon_status(alias: str, *, root: Path) -> dict[str, Any]:
    info = read_daemon_info(alias, root)
    if not info:
        return {"status": "not_running", "alias": alias}
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as sock:
            send_message(sock, {"action": "ping"})
            payload = recv_message(sock, timeout=5)
            payload["alias"] = alias
            return payload
    except Exception as exc:
        return {"status": "unreachable", "alias": alias, "error": str(exc)}


def daemon_stop(alias: str, *, root: Path) -> dict[str, Any]:
    info = read_daemon_info(alias, root)
    if not info:
        return {"status": "not_running", "alias": alias}
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as sock:
            send_message(sock, {"action": "shutdown"})
            payload = recv_message(sock, timeout=5)
        for _ in range(20):
            if not read_daemon_info(alias, root):
                break
            time.sleep(0.05)
        daemon_info_path(alias, root).unlink(missing_ok=True)
        return {"status": "stopped", "alias": alias, **payload}
    except Exception as exc:
        daemon_info_path(alias, root).unlink(missing_ok=True)
        return {"status": "force_cleaned", "alias": alias, "error": str(exc)}


def sftp_connect(
    connection: ConnectionConfig,
    *,
    config_path: Path,
    timeout: int,
    root: Path,
    save_name: str | None = None,
):
    client = connect_client(connection, config_path=config_path, timeout=timeout)
    try:
        if save_name:
            save_project_profile(save_name, connection, root=root)
        sftp = client.open_sftp()
        return client, sftp
    except Exception:
        close_ssh_client(client)
        raise


def remote_is_dir(sftp: Any, path: str) -> bool:
    try:
        return stat.S_ISDIR(sftp.stat(path).st_mode)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def remote_mkdir_p(sftp: Any, path: str) -> None:
    if not path or path == "/":
        return
    parts = [part for part in path.split("/") if part]
    current = "/" if path.startswith("/") else ""
    for part in parts:
        current = posixpath.join(current, part) if current else part
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def progress_printer(path: str, total: int, no_progress: bool):
    def callback(transferred: int, _total: int) -> None:
        if no_progress:
            return
        percent = round((transferred / total * 100), 2) if total else 100
        print(
            json.dumps(
                {"file": path, "transferred": transferred, "total": total, "percent": percent},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

    return callback


def upload_path(
    connection: ConnectionConfig,
    local_path: Path,
    remote_path: str,
    *,
    config_path: Path,
    root: Path,
    recursive: bool,
    no_progress: bool,
    save_name: str | None = None,
) -> dict[str, Any]:
    if not local_path.exists():
        raise SSHSkillError(f"Local path not found: {local_path}")
    client, sftp = sftp_connect(
        connection,
        config_path=config_path,
        timeout=30,
        root=root,
        save_name=save_name,
    )
    transferred_files = 0
    transferred_bytes = 0
    try:
        if local_path.is_dir():
            if not recursive:
                raise SSHSkillError(f"Local path is a directory; use --recursive: {local_path}")
            for file_path in sorted(item for item in local_path.rglob("*") if item.is_file()):
                relative = file_path.relative_to(local_path).as_posix()
                remote_file = posixpath.join(remote_path, relative)
                remote_mkdir_p(sftp, posixpath.dirname(remote_file))
                size = file_path.stat().st_size
                sftp.put(str(file_path), remote_file, callback=progress_printer(str(file_path), size, no_progress))
                transferred_files += 1
                transferred_bytes += size
        else:
            target = remote_path
            if target.endswith("/") or remote_is_dir(sftp, target):
                target = posixpath.join(target, local_path.name)
            remote_mkdir_p(sftp, posixpath.dirname(target))
            size = local_path.stat().st_size
            sftp.put(str(local_path), target, callback=progress_printer(str(local_path), size, no_progress))
            transferred_files = 1
            transferred_bytes = size
        return {
            "success": True,
            "operation": "upload",
            "files": transferred_files,
            "bytes": transferred_bytes,
            "local_path": str(local_path),
            "remote_path": remote_path,
        }
    finally:
        sftp.close()
        close_ssh_client(client)


def download_path(
    connection: ConnectionConfig,
    remote_path: str,
    local_path: Path,
    *,
    config_path: Path,
    root: Path,
    recursive: bool,
    no_progress: bool,
    save_name: str | None = None,
) -> dict[str, Any]:
    client, sftp = sftp_connect(
        connection,
        config_path=config_path,
        timeout=30,
        root=root,
        save_name=save_name,
    )
    transferred_files = 0
    transferred_bytes = 0
    try:
        if remote_is_dir(sftp, remote_path):
            if not recursive:
                raise SSHSkillError(f"Remote path is a directory; use --recursive: {remote_path}")
            local_path.mkdir(parents=True, exist_ok=True)
            stack = [(remote_path, local_path)]
            while stack:
                remote_dir, local_dir = stack.pop()
                local_dir.mkdir(parents=True, exist_ok=True)
                for attr in sftp.listdir_attr(remote_dir):
                    remote_item = posixpath.join(remote_dir, attr.filename)
                    local_item = local_dir / attr.filename
                    if stat.S_ISDIR(attr.st_mode):
                        stack.append((remote_item, local_item))
                    elif stat.S_ISREG(attr.st_mode):
                        size = int(attr.st_size)
                        sftp.get(remote_item, str(local_item), callback=progress_printer(remote_item, size, no_progress))
                        transferred_files += 1
                        transferred_bytes += size
        else:
            try:
                attrs = sftp.stat(remote_path)
            except OSError as exc:
                raise SSHSkillError(f"Remote path not found: {remote_path}") from exc
            target = local_path
            if local_path.exists() and local_path.is_dir():
                target = local_path / posixpath.basename(remote_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            size = int(attrs.st_size)
            sftp.get(remote_path, str(target), callback=progress_printer(remote_path, size, no_progress))
            transferred_files = 1
            transferred_bytes = size
        return {
            "success": True,
            "operation": "download",
            "files": transferred_files,
            "bytes": transferred_bytes,
            "remote_path": remote_path,
            "local_path": str(local_path),
        }
    finally:
        sftp.close()
        close_ssh_client(client)


def format_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def validate_positive_int(value: int | None, option: str) -> int | None:
    if value is None:
        return None
    if value <= 0:
        raise SSHSkillError(f"{option} must be greater than zero")
    return value


def resolve_project_output_path(path: Path, *, root: Path, option: str) -> Path:
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    resolved = candidate.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise SSHSkillError(f"{option} must be inside the project root: {root}") from exc
    return resolved


def prepare_output_path(
    path: Path | None,
    *,
    root: Path,
    option: str,
    overwrite: bool,
    append: bool = False,
) -> Path | None:
    if path is None:
        return None
    if overwrite and append:
        raise SSHSkillError(f"{option} cannot use overwrite and append together")
    resolved = resolve_project_output_path(path, root=root, option=option)
    if resolved.exists() and not overwrite and not append:
        raise SSHSkillError(
            f"{option} already exists; use the matching overwrite or append option: {resolved}"
        )
    return resolved


def open_interactive_log(path: Path | None, *, append: bool, overwrite: bool):
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if append else "wb" if overwrite else "xb"
    return path.open(mode)


def write_interactive_summary(path: Path | None, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def current_terminal_size(rows: int | None = None, cols: int | None = None) -> tuple[int, int]:
    if rows is not None and cols is not None:
        return rows, cols
    try:
        size = os.get_terminal_size(sys.stdin.fileno())
        terminal_rows = size.lines
        terminal_cols = size.columns
    except OSError:
        terminal_rows = 24
        terminal_cols = 80
    return rows or terminal_rows or 24, cols or terminal_cols or 80


def write_terminal_output(data: bytes, *, fd: int, log_handle: Any | None) -> None:
    if not data:
        return
    os.write(fd, data)
    if log_handle is not None:
        log_handle.write(data)
        log_handle.flush()


def drain_interactive_channel(channel: Any, *, stdout_fd: int, stderr_fd: int, log_handle: Any | None) -> None:
    while True:
        received = False
        if channel.recv_ready():
            data = channel.recv(BUFFER_SIZE)
            if data:
                write_terminal_output(data, fd=stdout_fd, log_handle=log_handle)
                received = True
        if channel.recv_stderr_ready():
            data = channel.recv_stderr(BUFFER_SIZE)
            if data:
                write_terminal_output(data, fd=stderr_fd, log_handle=log_handle)
                received = True
        if not received:
            return


def bridge_interactive_channel(
    channel: Any,
    *,
    shell_mode: bool,
    session_timeout: int | None,
    rows: int | None,
    cols: int | None,
    log_handle: Any | None,
) -> tuple[int, str]:
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    stderr_fd = sys.stderr.fileno()
    started = time.monotonic()
    old_attrs = termios.tcgetattr(stdin_fd)
    old_winch_handler = None

    def resize_pty(_signum: int | None = None, _frame: Any | None = None) -> None:
        resized_rows, resized_cols = current_terminal_size(rows, cols)
        try:
            channel.resize_pty(width=resized_cols, height=resized_rows)
        except Exception:
            pass

    try:
        tty.setraw(stdin_fd)
        if hasattr(signal, "SIGWINCH"):
            old_winch_handler = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, resize_pty)
        while True:
            if session_timeout is not None and time.monotonic() - started >= session_timeout:
                channel.close()
                return 255, "session timeout"

            try:
                readables, _, _ = select.select([stdin_fd, channel], [], [], 0.1)
            except InterruptedError:
                continue
            if channel in readables:
                drain_interactive_channel(
                    channel,
                    stdout_fd=stdout_fd,
                    stderr_fd=stderr_fd,
                    log_handle=log_handle,
                )
            if stdin_fd in readables:
                data = os.read(stdin_fd, BUFFER_SIZE)
                if not data or data == b"\x04":
                    try:
                        channel.shutdown_write()
                    except Exception:
                        pass
                else:
                    channel.sendall(data)

            drain_interactive_channel(
                channel,
                stdout_fd=stdout_fd,
                stderr_fd=stderr_fd,
                log_handle=log_handle,
            )
            if channel.exit_status_ready():
                return int(channel.recv_exit_status()), ""
            if channel.closed:
                if channel.exit_status_ready():
                    return int(channel.recv_exit_status()), ""
                if shell_mode:
                    return 0, ""
                return 255, "ssh channel closed without exit status"
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)
        if old_winch_handler is not None and hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, old_winch_handler)


def build_interactive_summary(
    *,
    target: str,
    shell_mode: bool,
    command: str | None,
    started_at: str,
    started_monotonic: float,
    exit_code: int,
    disconnect_reason: str,
) -> dict[str, Any]:
    ended_at = format_timestamp()
    duration = max(0, int(round(time.monotonic() - started_monotonic)))
    return {
        "success": exit_code == 0,
        "target": target,
        "mode": "shell" if shell_mode else "command",
        "command": command or "",
        "shell": shell_mode,
        "exit_code": exit_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration,
        "disconnect_reason": disconnect_reason,
    }


def run_interactive(
    connection: ConnectionConfig,
    *,
    command: str | None,
    shell_mode: bool,
    config_path: Path,
    connect_timeout: int,
    session_timeout: int | None,
    term: str,
    rows: int | None,
    cols: int | None,
    summary_path: Path | None,
    overwrite_summary: bool,
    log_path: Path | None,
    append_log: bool,
    overwrite_log: bool,
) -> int:
    started_at = format_timestamp()
    started_monotonic = time.monotonic()
    log_handle = None
    client = None
    channel = None

    def finish(exit_code: int, reason: str = "") -> int:
        summary = build_interactive_summary(
            target=connection.target,
            shell_mode=shell_mode,
            command=command,
            started_at=started_at,
            started_monotonic=started_monotonic,
            exit_code=exit_code,
            disconnect_reason=reason,
        )
        try:
            write_interactive_summary(summary_path, summary, overwrite=overwrite_summary)
        except Exception as exc:
            print(f"interactive summary write failed: {exc}", file=sys.stderr)
        if reason:
            print(f"interactive: {reason}", file=sys.stderr)
        return exit_code

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return finish(2, "interactive requires a local TTY; use exec for non-interactive commands")

    try:
        log_handle = open_interactive_log(log_path, append=append_log, overwrite=overwrite_log)
        client = connect_client(connection, config_path=config_path, timeout=connect_timeout)
        initial_rows, initial_cols = current_terminal_size(rows, cols)
        if shell_mode:
            channel = client.invoke_shell(
                term=term,
                width=initial_cols,
                height=initial_rows,
            )
        else:
            transport = client.get_transport()
            if not transport:
                return finish(255, "ssh transport is unavailable")
            channel = transport.open_session(timeout=connect_timeout)
            channel.get_pty(term=term, width=initial_cols, height=initial_rows)
            channel.exec_command(command or "")
        exit_code, reason = bridge_interactive_channel(
            channel,
            shell_mode=shell_mode,
            session_timeout=session_timeout,
            rows=rows,
            cols=cols,
            log_handle=log_handle,
        )
        return finish(exit_code, reason)
    except termios.error as exc:
        return finish(2, f"local TTY setup failed: {exc}")
    except Exception as exc:
        message = redact_secrets(f"{type(exc).__name__}: {exc}", {connection.password or ""})
        return finish(255, message)
    finally:
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
        if client is not None:
            close_ssh_client(client)


def command_from_remainder(parts: list[str]) -> str:
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        raise SSHSkillError("Missing remote command after --")
    if len(parts) == 1:
        return parts[0]
    return shlex.join(parts)


def _connection_options_from_args(args: argparse.Namespace) -> ConnectionOptions:
    return ConnectionOptions(
        username=getattr(args, "username", None),
        password=getattr(args, "password", None),
        password_stdin=bool(getattr(args, "password_stdin", False)),
        port=getattr(args, "port", None),
        save=bool(getattr(args, "save", False)),
        save_as=getattr(args, "save_as", None),
    )


def _value_after_option(parts: list[str], index: int, option: str) -> tuple[str, int]:
    if index + 1 >= len(parts):
        raise SSHSkillError(f"{option} requires a value")
    return parts[index + 1], index + 2


def normalize_exec_args(
    args: argparse.Namespace,
) -> tuple[str, int, bool, ConnectionOptions]:
    timeout = int(args.timeout)
    no_daemon = bool(args.no_daemon)
    options = _connection_options_from_args(args)
    command_parts = list(args.remote_command)
    normalized_parts: list[str] = []
    index = 0
    while index < len(command_parts):
        part = command_parts[index]
        if part == "--":
            normalized_parts.extend(command_parts[index:])
            break
        if part == "--no-daemon":
            no_daemon = True
            index += 1
            continue
        if part == "--username":
            options.username, index = _value_after_option(command_parts, index, part)
            continue
        if part.startswith("--username="):
            options.username = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--password":
            options.password, index = _value_after_option(command_parts, index, part)
            continue
        if part.startswith("--password="):
            options.password = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--password-stdin":
            options.password_stdin = True
            index += 1
            continue
        if part == "--port":
            raw_port, index = _value_after_option(command_parts, index, part)
            try:
                options.port = int(raw_port)
            except ValueError as exc:
                raise SSHSkillError("--port must be an integer") from exc
            continue
        if part.startswith("--port="):
            try:
                options.port = int(part.split("=", 1)[1])
            except ValueError as exc:
                raise SSHSkillError("--port must be an integer") from exc
            index += 1
            continue
        if part == "--save":
            options.save = True
            index += 1
            continue
        if part == "--save-as":
            options.save_as, index = _value_after_option(command_parts, index, part)
            continue
        if part.startswith("--save-as="):
            options.save_as = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--timeout":
            if index + 1 >= len(command_parts):
                raise SSHSkillError("--timeout requires a value")
            try:
                timeout = int(command_parts[index + 1])
            except ValueError as exc:
                raise SSHSkillError("--timeout must be an integer") from exc
            index += 2
            continue
        if part.startswith("--timeout="):
            try:
                timeout = int(part.split("=", 1)[1])
            except ValueError as exc:
                raise SSHSkillError("--timeout must be an integer") from exc
            index += 1
            continue
        normalized_parts.extend(command_parts[index:])
        break
    return (
        command_from_remainder(normalized_parts),
        timeout,
        no_daemon,
        prepare_connection_options(options),
    )


def interactive_command_from_argv(argv: list[str]) -> tuple[bool, list[str]]:
    try:
        index = argv.index("interactive")
    except ValueError:
        return False, []
    tail = argv[index + 1 :]
    if "--" not in tail:
        return False, []
    separator_index = tail.index("--")
    return True, tail[separator_index + 1 :]


def _set_int_arg(args: argparse.Namespace, name: str, raw_value: str, option: str) -> None:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SSHSkillError(f"{option} must be an integer") from exc
    setattr(args, name, value)


def normalize_interactive_args(
    args: argparse.Namespace,
    *,
    separator_present: bool,
    remote_command: list[str],
) -> tuple[str | None, bool, ConnectionOptions]:
    command_parts = list(args.remote_command)
    if separator_present and "--" in command_parts:
        local_parts = command_parts[: command_parts.index("--")]
    elif separator_present:
        local_parts = []
    else:
        local_parts = command_parts
    index = 0
    while index < len(local_parts):
        part = local_parts[index]
        if part == "--username":
            args.username, index = _value_after_option(local_parts, index, part)
            continue
        if part.startswith("--username="):
            args.username = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--password":
            args.password, index = _value_after_option(local_parts, index, part)
            continue
        if part.startswith("--password="):
            args.password = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--password-stdin":
            args.password_stdin = True
            index += 1
            continue
        if part == "--port":
            raw_port, index = _value_after_option(local_parts, index, part)
            _set_int_arg(args, "port", raw_port, part)
            continue
        if part.startswith("--port="):
            _set_int_arg(args, "port", part.split("=", 1)[1], "--port")
            index += 1
            continue
        if part == "--connect-timeout":
            raw_timeout, index = _value_after_option(local_parts, index, part)
            _set_int_arg(args, "connect_timeout", raw_timeout, part)
            continue
        if part.startswith("--connect-timeout="):
            _set_int_arg(args, "connect_timeout", part.split("=", 1)[1], "--connect-timeout")
            index += 1
            continue
        if part == "--session-timeout":
            raw_timeout, index = _value_after_option(local_parts, index, part)
            _set_int_arg(args, "session_timeout", raw_timeout, part)
            continue
        if part.startswith("--session-timeout="):
            _set_int_arg(args, "session_timeout", part.split("=", 1)[1], "--session-timeout")
            index += 1
            continue
        if part == "--term":
            args.term, index = _value_after_option(local_parts, index, part)
            continue
        if part.startswith("--term="):
            args.term = part.split("=", 1)[1]
            index += 1
            continue
        if part == "--rows":
            raw_rows, index = _value_after_option(local_parts, index, part)
            _set_int_arg(args, "rows", raw_rows, part)
            continue
        if part.startswith("--rows="):
            _set_int_arg(args, "rows", part.split("=", 1)[1], "--rows")
            index += 1
            continue
        if part == "--cols":
            raw_cols, index = _value_after_option(local_parts, index, part)
            _set_int_arg(args, "cols", raw_cols, part)
            continue
        if part.startswith("--cols="):
            _set_int_arg(args, "cols", part.split("=", 1)[1], "--cols")
            index += 1
            continue
        if part == "--shell":
            args.shell = True
            index += 1
            continue
        if part == "--summary-file":
            raw_path, index = _value_after_option(local_parts, index, part)
            args.summary_file = Path(raw_path)
            continue
        if part.startswith("--summary-file="):
            args.summary_file = Path(part.split("=", 1)[1])
            index += 1
            continue
        if part == "--overwrite-summary":
            args.overwrite_summary = True
            index += 1
            continue
        if part == "--log-file":
            raw_path, index = _value_after_option(local_parts, index, part)
            args.log_file = Path(raw_path)
            continue
        if part.startswith("--log-file="):
            args.log_file = Path(part.split("=", 1)[1])
            index += 1
            continue
        if part == "--append-log":
            args.append_log = True
            index += 1
            continue
        if part == "--overwrite-log":
            args.overwrite_log = True
            index += 1
            continue
        raise SSHSkillError(f"Unknown interactive option before --: {part}")

    if args.append_log and args.overwrite_log:
        raise SSHSkillError("--append-log and --overwrite-log cannot be used together")

    options = prepare_connection_options(_connection_options_from_args(args))
    shell_mode = bool(args.shell)
    if shell_mode:
        if separator_present and remote_command:
            raise SSHSkillError("--shell cannot be combined with a remote command")
        return None, True, options
    if not separator_present:
        raise SSHSkillError("interactive requires -- <remote command> or --shell")
    return command_from_remainder(remote_command), False, options


def add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username", help="SSH username")
    parser.add_argument(
        "--password",
        help="SSH password (may be exposed in shell history and process listings)",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--port", type=int, help="SSH port")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the successfully authenticated username/password in the current project",
    )
    parser.add_argument("--save-as", help="Project credential profile name; requires --save")


def add_interactive_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username", help="SSH username")
    parser.add_argument(
        "--password",
        help="SSH password (may be exposed in shell history and process listings)",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--port", type=int, help="SSH port")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSH skill CLI")
    parser.add_argument("--config", type=Path, default=default_config_path(), help="SSH config path")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root for daemon state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List project credential profiles and SSH Host aliases")

    find_parser = subparsers.add_parser("find", help="Find SSH Host aliases")
    find_parser.add_argument("keyword")

    test_parser = subparsers.add_parser("test", help="Test an SSH connection")
    test_parser.add_argument("target")
    test_parser.add_argument("--timeout", type=int, default=30)
    add_connection_arguments(test_parser)

    exec_parser = subparsers.add_parser("exec", help="Execute a remote command")
    exec_parser.add_argument("target")
    exec_parser.add_argument("--timeout", type=int, default=30)
    exec_parser.add_argument("--no-daemon", action="store_true")
    add_connection_arguments(exec_parser)
    exec_parser.add_argument("remote_command", nargs=argparse.REMAINDER)

    interactive_parser = subparsers.add_parser(
        "interactive",
        help="Run a remote command or shell through a local interactive PTY",
    )
    interactive_parser.add_argument("target")
    add_interactive_connection_arguments(interactive_parser)
    interactive_parser.add_argument("--connect-timeout", type=int, default=30)
    interactive_parser.add_argument("--session-timeout", type=int)
    interactive_parser.add_argument("--term")
    interactive_parser.add_argument("--rows", type=int)
    interactive_parser.add_argument("--cols", type=int)
    interactive_parser.add_argument("--shell", action="store_true")
    interactive_parser.add_argument("--summary-file", type=Path)
    interactive_parser.add_argument("--overwrite-summary", action="store_true")
    interactive_parser.add_argument("--log-file", type=Path)
    log_group = interactive_parser.add_mutually_exclusive_group()
    log_group.add_argument("--append-log", action="store_true")
    log_group.add_argument("--overwrite-log", action="store_true")
    interactive_parser.add_argument("remote_command", nargs=argparse.REMAINDER)

    upload_parser = subparsers.add_parser("upload", help="Upload a file or directory")
    upload_parser.add_argument("target")
    upload_parser.add_argument("local_path", type=Path)
    upload_parser.add_argument("remote_path")
    upload_parser.add_argument("--recursive", action="store_true")
    upload_parser.add_argument("--no-progress", action="store_true")
    add_connection_arguments(upload_parser)

    download_parser = subparsers.add_parser("download", help="Download a file or directory")
    download_parser.add_argument("target")
    download_parser.add_argument("remote_path")
    download_parser.add_argument("local_path", type=Path)
    download_parser.add_argument("--recursive", action="store_true")
    download_parser.add_argument("--no-progress", action="store_true")
    add_connection_arguments(download_parser)

    credentials_parser = subparsers.add_parser(
        "credentials",
        help="List or remove project SSH credential profiles",
    )
    credentials_parser.add_argument("action", choices=["list", "remove"])
    credentials_parser.add_argument("name", nargs="?")

    control_parser = subparsers.add_parser("control", help="Manage the daemon")
    control_parser.add_argument("action", choices=["status", "stop"])
    control_parser.add_argument("alias")

    daemon_parser = subparsers.add_parser("daemon", help=argparse.SUPPRESS)
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    start_parser = daemon_subparsers.add_parser("start")
    start_parser.add_argument("alias")
    start_parser.add_argument("--idle-timeout", type=int, default=IDLE_TIMEOUT_SECONDS)

    return parser


def redact_secrets(message: str, secrets: set[str]) -> str:
    redacted = message
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_argv)
    config_path = Path(args.config).expanduser()
    root = Path(args.root).resolve()
    secret_values: set[str] = set()

    try:
        try:
            secret_values.update(
                profile.password for profile in load_project_profiles(root).values()
            )
        except SSHSkillError:
            pass
        if args.command == "list":
            json_print(
                {
                    "success": True,
                    "operation": "list",
                    "targets": list_targets(config_path=config_path, root=root),
                }
            )
            return 0
        if args.command == "find":
            json_print(
                {
                    "success": True,
                    "operation": "find",
                    "keyword": args.keyword,
                    "targets": find_targets(args.keyword, config_path=config_path, root=root),
                }
            )
            return 0
        if args.command == "credentials":
            if args.action == "list":
                if args.name is not None:
                    raise SSHSkillError("credentials list does not accept a profile name")
                json_print(
                    {
                        "success": True,
                        "operation": "credentials_list",
                        "profiles": [
                            profile.as_dict()
                            for profile in sorted(
                                load_project_profiles(root).values(),
                                key=lambda item: item.name.lower(),
                            )
                        ],
                    }
                )
                return 0
            if not args.name:
                raise SSHSkillError("credentials remove requires a profile name")
            result = remove_project_profile(args.name, root=root)
            result["operation"] = "credentials_remove"
            json_print(result)
            return 0 if result["removed"] else 1
        if args.command == "test":
            options = prepare_connection_options(_connection_options_from_args(args))
            if options.password:
                secret_values.add(options.password)
            connection = resolve_connection(
                args.target,
                config_path=config_path,
                root=root,
                options=options,
            )
            if connection.password:
                secret_values.add(connection.password)
            ensure_paramiko()
            client = connect_client(connection, config_path=config_path, timeout=args.timeout)
            try:
                if options.save:
                    save_project_profile(options.save_as or args.target, connection, root=root)
            finally:
                close_ssh_client(client)
            json_print(
                {
                    "success": True,
                    "operation": "test",
                    "target": args.target,
                    "source": connection.source,
                }
            )
            return 0
        if args.command == "exec":
            command, timeout, no_daemon, options = normalize_exec_args(args)
            if options.password:
                secret_values.add(options.password)
            connection = resolve_connection(
                args.target,
                config_path=config_path,
                root=root,
                options=options,
            )
            if connection.password:
                secret_values.add(connection.password)
            ensure_paramiko()
            result = None
            use_daemon = not (
                no_daemon
                or options.has_explicit_connection_values()
                or options.save
            )
            if use_daemon:
                result = try_daemon_execute(args.target, command, root=root, timeout=timeout)
                if result is None and start_daemon_background(
                    args.target,
                    config_path=config_path,
                    root=root,
                    idle_timeout=IDLE_TIMEOUT_SECONDS,
                ):
                    result = try_daemon_execute(args.target, command, root=root, timeout=timeout)
            if result is None:
                result = execute_direct(
                    connection,
                    command,
                    config_path=config_path,
                    timeout=timeout,
                    root=root,
                    save_name=(options.save_as or args.target) if options.save else None,
                )
            result["operation"] = "exec"
            json_print(result)
            return 0 if result.get("success") else 1
        if args.command == "interactive":
            separator_present, remote_command = interactive_command_from_argv(raw_argv)
            command, shell_mode, options = normalize_interactive_args(
                args,
                separator_present=separator_present,
                remote_command=remote_command,
            )
            if options.password:
                secret_values.add(options.password)
            connect_timeout = validate_positive_int(args.connect_timeout, "--connect-timeout")
            session_timeout = validate_positive_int(args.session_timeout, "--session-timeout")
            rows = validate_positive_int(args.rows, "--rows")
            cols = validate_positive_int(args.cols, "--cols")
            summary_path = prepare_output_path(
                args.summary_file,
                root=root,
                option="--summary-file",
                overwrite=bool(args.overwrite_summary),
            )
            log_path = prepare_output_path(
                args.log_file,
                root=root,
                option="--log-file",
                overwrite=bool(args.overwrite_log),
                append=bool(args.append_log),
            )
            term = (args.term or os.environ.get("TERM") or "xterm-256color").strip()
            if not term:
                term = "xterm-256color"
            connection = resolve_connection(
                args.target,
                config_path=config_path,
                root=root,
                options=options,
            )
            if connection.password:
                secret_values.add(connection.password)
            ensure_paramiko()
            return run_interactive(
                connection,
                command=command,
                shell_mode=shell_mode,
                config_path=config_path,
                connect_timeout=int(connect_timeout or 30),
                session_timeout=session_timeout,
                term=term,
                rows=rows,
                cols=cols,
                summary_path=summary_path,
                overwrite_summary=bool(args.overwrite_summary),
                log_path=log_path,
                append_log=bool(args.append_log),
                overwrite_log=bool(args.overwrite_log),
            )
        if args.command == "upload":
            options = prepare_connection_options(_connection_options_from_args(args))
            if options.password:
                secret_values.add(options.password)
            connection = resolve_connection(
                args.target,
                config_path=config_path,
                root=root,
                options=options,
            )
            if connection.password:
                secret_values.add(connection.password)
            ensure_paramiko()
            result = upload_path(
                connection,
                args.local_path,
                args.remote_path,
                config_path=config_path,
                root=root,
                recursive=args.recursive,
                no_progress=args.no_progress,
                save_name=(options.save_as or args.target) if options.save else None,
            )
            json_print(result)
            return 0
        if args.command == "download":
            options = prepare_connection_options(_connection_options_from_args(args))
            if options.password:
                secret_values.add(options.password)
            connection = resolve_connection(
                args.target,
                config_path=config_path,
                root=root,
                options=options,
            )
            if connection.password:
                secret_values.add(connection.password)
            ensure_paramiko()
            result = download_path(
                connection,
                args.remote_path,
                args.local_path,
                config_path=config_path,
                root=root,
                recursive=args.recursive,
                no_progress=args.no_progress,
                save_name=(options.save_as or args.target) if options.save else None,
            )
            json_print(result)
            return 0
        if args.command == "control":
            payload = daemon_status(args.alias, root=root) if args.action == "status" else daemon_stop(args.alias, root=root)
            payload["success"] = payload.get("status") != "unreachable"
            payload["operation"] = f"control_{args.action}"
            json_print(payload)
            return 0
        if args.command == "daemon" and args.daemon_command == "start":
            ensure_paramiko()
            daemon = SSHDaemon(args.alias, config_path=config_path, root=root, idle_timeout=args.idle_timeout)
            daemon.start()
            return 0
    except DependencyError as exc:
        return json_error(redact_secrets(str(exc), secret_values), exit_code=2)
    except SSHSkillError as exc:
        return json_error(redact_secrets(str(exc), secret_values), exit_code=1)
    except Exception as exc:
        message = redact_secrets(f"{type(exc).__name__}: {exc}", secret_values)
        return json_error(message, exit_code=1)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
