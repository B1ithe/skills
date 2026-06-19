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
PROFILES_SCHEMA_VERSION = 1
PROFILES_FILE_NAME = "profiles.json"
PROFILES_GITIGNORE_ENTRY = f"/{PROFILES_FILE_NAME}"
AUTH_PASSWORD = "password"
AUTH_IDENTITY_FILE = "identity-file"


class SSHSkillError(Exception):
    pass


class DependencyError(SSHSkillError):
    pass


@dataclass
class ProjectProfile:
    name: str
    hostname: str
    username: str
    auth: str
    password: str | None = field(default=None, repr=False)
    identity_file: str | None = None
    port: int = 22

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "alias": self.name,
            "hostname": self.hostname,
            "user": self.username,
            "username": self.username,
            "port": self.port,
            "auth": self.auth,
            "source": "project-profile",
        }
        if self.auth == AUTH_IDENTITY_FILE:
            payload["identity_file"] = self.identity_file
        return payload

    def to_connection(self) -> "ConnectionConfig":
        return ConnectionConfig(
            target=self.name,
            hostname=self.hostname,
            username=self.username,
            port=self.port,
            password=self.password,
            identity_file=self.identity_file,
            source="project-profile",
        )


@dataclass
class ConnectionConfig:
    target: str
    hostname: str
    username: str | None = None
    port: int = 22
    password: str | None = field(default=None, repr=False)
    identity_file: str | None = None
    source: str = "direct"

    def has_auth(self) -> bool:
        return self.password is not None or self.identity_file is not None


@dataclass
class ConnectionOptions:
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    identity_file: str | None = None
    port: int | None = None
    save: bool = False
    save_as: str | None = None


def script_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ssh_skill_state_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / ".ssh-skill"


def profiles_path(root: Path | None = None) -> Path:
    return ssh_skill_state_dir(root) / PROFILES_FILE_NAME


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
        raise SSHSkillError("Profile name must not be empty")
    if any(ord(character) < 32 for character in normalized):
        raise SSHSkillError("Profile name must not contain control characters")
    return normalized


def normalize_identity_file_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise SSHSkillError("--identity-file requires a non-empty path")
    return str(Path(normalized).expanduser().resolve(strict=False))


def validate_identity_file(path: str) -> str:
    normalized = normalize_identity_file_path(path)
    identity_path = Path(normalized)
    if not identity_path.exists():
        raise SSHSkillError(f"Identity file not found: {normalized}")
    if not identity_path.is_file():
        raise SSHSkillError(f"Identity file is not a file: {normalized}")
    return normalized


def validate_connection_auth_files(connection: ConnectionConfig) -> None:
    if connection.identity_file is not None:
        connection.identity_file = validate_identity_file(connection.identity_file)


def _check_profiles_file_security(path: Path) -> None:
    if path.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked profiles file: {path}")
    if not path.exists() or os.name == "nt":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SSHSkillError(
            f"Profiles file permissions are too broad: {path} has mode {mode:04o}; expected 0600"
        )


def _ensure_profiles_directory(root: Path) -> Path:
    directory = ssh_skill_state_dir(root)
    if directory.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked SSH skill state directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


def load_project_profiles(root: Path | None = None) -> dict[str, ProjectProfile]:
    project_root = root or Path.cwd()
    path = profiles_path(project_root)
    if not path.exists() and not path.is_symlink():
        return {}
    _check_profiles_file_security(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SSHSkillError(f"Unable to read SSH profiles: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PROFILES_SCHEMA_VERSION:
        raise SSHSkillError(
            f"Unsupported SSH profiles schema in {path}; expected schema_version "
            f"{PROFILES_SCHEMA_VERSION}"
        )
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict):
        raise SSHSkillError(f"Invalid SSH profiles in {path}")

    profiles: dict[str, ProjectProfile] = {}
    for raw_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_name, str) or not isinstance(raw_profile, dict):
            raise SSHSkillError(f"Invalid SSH profile in {path}")
        name = validate_profile_name(raw_name)
        hostname = raw_profile.get("hostname")
        username = raw_profile.get("username")
        auth = raw_profile.get("auth")
        password = raw_profile.get("password")
        identity_file = raw_profile.get("identity_file")
        port = raw_profile.get("port", 22)
        if not isinstance(hostname, str) or not hostname.strip():
            raise SSHSkillError(f"Profile {name!r} has an invalid hostname")
        if not isinstance(username, str) or not username.strip():
            raise SSHSkillError(f"Profile {name!r} has an invalid username")
        if auth not in {AUTH_PASSWORD, AUTH_IDENTITY_FILE}:
            raise SSHSkillError(
                f"Profile {name!r} has an invalid auth; expected {AUTH_PASSWORD!r} or {AUTH_IDENTITY_FILE!r}"
            )
        if auth == AUTH_PASSWORD:
            if not isinstance(password, str) or not password:
                raise SSHSkillError(f"Profile {name!r} has an invalid password")
            identity_file = None
        else:
            if not isinstance(identity_file, str) or not identity_file.strip():
                raise SSHSkillError(f"Profile {name!r} has an invalid identity_file")
            password = None
            identity_file = normalize_identity_file_path(identity_file)
        if not isinstance(port, int) or isinstance(port, bool):
            raise SSHSkillError(f"Profile {name!r} has an invalid port")
        profiles[name] = ProjectProfile(
            name=name,
            hostname=hostname.strip(),
            username=username.strip(),
            auth=auth,
            password=password,
            identity_file=identity_file,
            port=validate_port(port),
        )
    return profiles


def _write_profiles_gitignore(directory: Path) -> None:
    path = directory / ".gitignore"
    if path.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked SSH skill gitignore: {path}")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    if PROFILES_GITIGNORE_ENTRY in lines:
        return
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(f"{prefix}{PROFILES_GITIGNORE_ENTRY}\n", encoding="utf-8")


def write_project_profiles(profiles: dict[str, ProjectProfile], root: Path | None = None) -> None:
    project_root = root or Path.cwd()
    directory = _ensure_profiles_directory(project_root)
    path = profiles_path(project_root)
    if path.exists() or path.is_symlink():
        _check_profiles_file_security(path)
    _write_profiles_gitignore(directory)
    payload = {
        "schema_version": PROFILES_SCHEMA_VERSION,
        "profiles": {
            name: {
                "hostname": profile.hostname,
                "port": profile.port,
                "username": profile.username,
                "auth": profile.auth,
                **(
                    {"password": profile.password}
                    if profile.auth == AUTH_PASSWORD
                    else {"identity_file": profile.identity_file}
                ),
            }
            for name, profile in sorted(profiles.items())
        },
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{PROFILES_FILE_NAME}.",
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
    stop_daemons: bool = True,
) -> ProjectProfile:
    profile_name = validate_profile_name(name)
    if not connection.username:
        raise SSHSkillError("Saving an SSH profile requires a username")
    if connection.password and connection.identity_file:
        raise SSHSkillError(
            "Saving an SSH profile requires either password or identity_file, not both"
        )
    if not connection.password and not connection.identity_file:
        raise SSHSkillError("Saving an SSH profile requires --password or --identity-file")
    auth = AUTH_PASSWORD if connection.password is not None else AUTH_IDENTITY_FILE
    profile = ProjectProfile(
        name=profile_name,
        hostname=connection.hostname,
        username=connection.username,
        auth=auth,
        password=connection.password,
        identity_file=(
            normalize_identity_file_path(connection.identity_file)
            if connection.identity_file
            else None
        ),
        port=connection.port,
    )
    profiles = load_project_profiles(root)
    old_profile = profiles.get(profile_name)
    if stop_daemons and old_profile is not None:
        daemon_stop(old_profile.to_connection(), root=root)
    profiles[profile_name] = profile
    if stop_daemons:
        daemon_stop(profile.to_connection(), root=root)
    write_project_profiles(profiles, root)
    return profile


def remove_project_profile(name: str, *, root: Path) -> dict[str, Any]:
    profile_name = validate_profile_name(name)
    profiles = load_project_profiles(root)
    if profile_name not in profiles:
        return {"success": False, "removed": False, "name": profile_name}
    daemon_stop(profiles[profile_name].to_connection(), root=root)
    del profiles[profile_name]
    write_project_profiles(profiles, root)
    return {"success": True, "removed": True, "name": profile_name}


def list_targets(*, root: Path) -> list[dict[str, Any]]:
    profiles = load_project_profiles(root)
    return sorted(
        (profile.as_dict() for profile in profiles.values()),
        key=lambda item: str(item["alias"]).lower(),
    )


def find_targets(keyword: str, *, root: Path) -> list[dict[str, Any]]:
    needle = keyword.lower()
    matches: list[dict[str, Any]] = []
    for target in list_targets(root=root):
        haystack = [
            target.get("alias", ""),
            target.get("hostname", ""),
            target.get("user", ""),
            target.get("username", ""),
            target.get("auth", ""),
            target.get("identity_file", ""),
        ]
        if any(needle in str(value).lower() for value in haystack):
            matches.append(target)
    return matches


def prepare_connection_options(options: ConnectionOptions) -> ConnectionOptions:
    if options.save_as is not None and not options.save:
        raise SSHSkillError("--save-as requires --save")
    password = options.password
    if password == "":
        raise SSHSkillError("--password requires a non-empty password")
    identity_file = options.identity_file
    if identity_file == "":
        raise SSHSkillError("--identity-file requires a non-empty path")
    if password is not None and identity_file is not None:
        raise SSHSkillError("--password and --identity-file cannot be used together")
    if options.port is not None:
        validate_port(options.port)
    return ConnectionOptions(
        username=options.username,
        password=password,
        identity_file=normalize_identity_file_path(identity_file) if identity_file is not None else None,
        port=options.port,
        save=options.save,
        save_as=options.save_as,
    )


def resolve_connection(
    target: str,
    *,
    root: Path,
    options: ConnectionOptions | None = None,
    require_auth: bool = False,
) -> ConnectionConfig:
    if not target.strip():
        raise SSHSkillError("SSH target must not be empty")
    overrides = options or ConnectionOptions()
    profiles = load_project_profiles(root)
    if target in profiles:
        connection = profiles[target].to_connection()
    else:
        connection = ConnectionConfig(
            target=target,
            hostname=target.strip(),
            source="direct",
        )

    if overrides.username is not None:
        username = overrides.username.strip()
        if not username:
            raise SSHSkillError("--username requires a non-empty value")
        connection.username = username
    if overrides.password is not None:
        connection.password = overrides.password
        connection.identity_file = None
    if overrides.identity_file is not None:
        connection.identity_file = overrides.identity_file
        connection.password = None
    if overrides.port is not None:
        connection.port = validate_port(overrides.port)

    if not connection.username:
        raise SSHSkillError("Direct SSH targets require --username unless the target is a saved profile")
    if connection.password and connection.identity_file:
        raise SSHSkillError("Connection cannot use both password and identity_file")
    if connection.password and not connection.username:
        raise SSHSkillError(
            "Password authentication requires a username via --username or a saved profile"
        )
    if require_auth and not connection.has_auth():
        raise SSHSkillError(
            "No authentication available; provide --password, --identity-file, or use a saved profile"
        )
    if overrides.save:
        if not connection.username:
            raise SSHSkillError("Saving an SSH profile requires a username")
        if not connection.has_auth():
            raise SSHSkillError("Saving an SSH profile requires --password or --identity-file")
        validate_profile_name(overrides.save_as or target)
    return connection


def resolve_control_connection(target: str, *, root: Path, username: str | None, port: int | None) -> ConnectionConfig:
    options = ConnectionOptions(username=username, port=port)
    return resolve_connection(
        target,
        root=root,
        options=prepare_connection_options(options),
        require_auth=False,
    )


def daemon_state_dir(root: Path | None = None) -> Path:
    return ssh_skill_state_dir(root) / "daemon"


def ensure_daemon_directory(root: Path) -> Path:
    directory = daemon_state_dir(root)
    if directory.is_symlink():
        raise SSHSkillError(f"Refusing to use symlinked SSH skill daemon directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


def daemon_key(hostname: str, port: int, username: str) -> str:
    return f"{hostname.strip().lower()}:{validate_port(port)}:{username.strip()}"


def daemon_key_for_connection(connection: ConnectionConfig) -> str:
    if not connection.username:
        raise SSHSkillError("Daemon lookup requires a username")
    return daemon_key(connection.hostname, connection.port, connection.username)


def daemon_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def daemon_info_path(key: str, root: Path | None = None) -> Path:
    return daemon_state_dir(root) / f"{daemon_id(key)}.json"


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_daemon_info(key: str, root: Path | None = None) -> dict[str, Any] | None:
    path = daemon_info_path(key, root)
    if not path.exists():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        path.unlink(missing_ok=True)
        return None
    if info.get("key") != key:
        path.unlink(missing_ok=True)
        return None
    pid = info.get("pid")
    if isinstance(pid, int) and is_process_alive(pid):
        return info
    path.unlink(missing_ok=True)
    return None


def write_daemon_info(key: str, info: dict[str, Any], root: Path | None = None) -> None:
    directory = ensure_daemon_directory(root or Path.cwd())
    daemon_info_path(key, root).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


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


def connect_client(connection: ConnectionConfig, *, timeout: int):
    if not connection.has_auth():
        raise SSHSkillError("Connection requires --password, --identity-file, or a saved profile")
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
        "allow_agent": False,
        "look_for_keys": False,
    }
    if connection.identity_file is not None:
        connect_kwargs["key_filename"] = validate_identity_file(connection.identity_file)
    if connection.password is not None:
        connect_kwargs["password"] = connection.password
    client.connect(**connect_kwargs)
    return client


def connect_target(
    connection: ConnectionConfig,
    *,
    timeout: int,
) -> tuple[ConnectionConfig, Any]:
    return connection, connect_client(connection, timeout=timeout)


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


def read_exec_result(stdout: Any, stderr: Any, *, timeout: int) -> tuple[int, str, str]:
    channel = stdout.channel
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout if timeout > 0 else None

    while True:
        while channel.recv_ready():
            stdout_chunks.append(channel.recv(BUFFER_SIZE))
        while channel.recv_stderr_ready():
            stderr_chunks.append(channel.recv_stderr(BUFFER_SIZE))
        if channel.exit_status_ready():
            while channel.recv_ready():
                stdout_chunks.append(channel.recv(BUFFER_SIZE))
            while channel.recv_stderr_ready():
                stderr_chunks.append(channel.recv_stderr(BUFFER_SIZE))
            exit_code = int(channel.recv_exit_status())
            return (
                exit_code,
                b"".join(stdout_chunks).decode("utf-8", errors="replace"),
                b"".join(stderr_chunks).decode("utf-8", errors="replace"),
            )
        if deadline is not None and time.monotonic() >= deadline:
            channel.close()
            raise SSHSkillError(f"Remote command timed out after {timeout} seconds")
        time.sleep(0.05)


def execute_direct(
    connection: ConnectionConfig,
    command: str,
    *,
    timeout: int,
    root: Path,
    save_name: str | None = None,
) -> dict[str, Any]:
    client = connect_client(connection, timeout=timeout)
    try:
        if save_name:
            save_project_profile(save_name, connection, root=root)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code, stdout_text, stderr_text = read_exec_result(stdout, stderr, timeout=timeout)
        return {
            "success": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "method": "direct",
        }
    finally:
        close_ssh_client(client)


def connection_to_payload(connection: ConnectionConfig) -> dict[str, Any]:
    return {
        "target": connection.target,
        "hostname": connection.hostname,
        "username": connection.username,
        "port": connection.port,
        "password": connection.password,
        "identity_file": connection.identity_file,
        "source": connection.source,
    }


def connection_from_payload(payload: dict[str, Any]) -> ConnectionConfig:
    hostname = payload.get("hostname")
    username = payload.get("username")
    port = payload.get("port", 22)
    password = payload.get("password")
    identity_file = payload.get("identity_file")
    target = payload.get("target") or hostname
    source = payload.get("source") or "direct"
    if not isinstance(hostname, str) or not hostname.strip():
        raise SSHSkillError("Daemon start file has an invalid hostname")
    if not isinstance(username, str) or not username.strip():
        raise SSHSkillError("Daemon start file has an invalid username")
    if not isinstance(port, int) or isinstance(port, bool):
        raise SSHSkillError("Daemon start file has an invalid port")
    if password is not None and not isinstance(password, str):
        raise SSHSkillError("Daemon start file has an invalid password")
    if identity_file is not None and not isinstance(identity_file, str):
        raise SSHSkillError("Daemon start file has an invalid identity_file")
    if password and identity_file:
        raise SSHSkillError("Daemon start file cannot contain both password and identity_file")
    return ConnectionConfig(
        target=str(target),
        hostname=hostname.strip(),
        username=username.strip(),
        port=validate_port(port),
        password=password,
        identity_file=normalize_identity_file_path(identity_file) if identity_file else None,
        source=str(source),
    )


def write_daemon_start_file(connection: ConnectionConfig, *, root: Path) -> Path:
    directory = ensure_daemon_directory(root)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"start-{daemon_id(daemon_key_for_connection(connection))}-",
        suffix=".json",
        dir=directory,
    )
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(connection_to_payload(connection), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def read_daemon_start_file(path: Path) -> ConnectionConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SSHSkillError(f"Unable to read daemon start file: {path}") from exc
    finally:
        path.unlink(missing_ok=True)
    if not isinstance(payload, dict):
        raise SSHSkillError(f"Invalid daemon start file: {path}")
    return connection_from_payload(payload)


def request_daemon(info: dict[str, Any], payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as sock:
        send_message(sock, payload)
        return recv_message(sock, timeout=timeout)


def live_daemon_info(key: str, root: Path) -> dict[str, Any] | None:
    info = read_daemon_info(key, root)
    if not info:
        return None
    try:
        payload = request_daemon(info, {"action": "ping"}, timeout=5)
        if payload.get("key") != key:
            daemon_info_path(key, root).unlink(missing_ok=True)
            return None
        return info
    except Exception:
        daemon_info_path(key, root).unlink(missing_ok=True)
        return None


def try_daemon_execute(connection: ConnectionConfig, command: str, *, root: Path, timeout: int) -> dict[str, Any] | None:
    key = daemon_key_for_connection(connection)
    info = read_daemon_info(key, root)
    if not info:
        return None
    try:
        result = request_daemon(
            info,
            {"action": "execute", "command": command, "timeout": timeout},
            timeout=timeout + 5,
        )
        result["method"] = "daemon"
        return result
    except Exception:
        daemon_info_path(key, root).unlink(missing_ok=True)
        return None


def start_daemon_background(connection: ConnectionConfig, *, root: Path, idle_timeout: int) -> bool:
    key = daemon_key_for_connection(connection)
    if live_daemon_info(key, root):
        return True
    start_file = write_daemon_start_file(connection, root=root)
    script = Path(__file__).resolve()
    cmd = [
        sys.executable,
        str(script),
        "--root",
        str(root),
        "daemon",
        "start",
        "--start-file",
        str(start_file),
        "--idle-timeout",
        str(idle_timeout),
    ]
    with open(os.devnull, "wb") as devnull:
        subprocess.Popen(cmd, stdout=devnull, stderr=devnull, start_new_session=(os.name != "nt"))
    for _ in range(20):
        time.sleep(0.2)
        if live_daemon_info(key, root):
            return True
    start_file.unlink(missing_ok=True)
    return False


class SSHDaemon:
    def __init__(self, connection: ConnectionConfig, *, root: Path, idle_timeout: int):
        self.connection = connection
        self.key = daemon_key_for_connection(connection)
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
        if live_daemon_info(self.key, self.root):
            return
        atexit.register(self.shutdown)
        _connection, self.ssh_client = connect_target(self.connection, timeout=30)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(5)
        self.server_socket.settimeout(5.0)
        port = self.server_socket.getsockname()[1]
        self.running = True
        write_daemon_info(
            self.key,
            {
                "key": self.key,
                "pid": os.getpid(),
                "port": port,
                "hostname": self.connection.hostname,
                "ssh_port": self.connection.port,
                "username": self.connection.username,
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
                timeout = int(
                    validate_positive_int(int(request.get("timeout", 30)), "timeout") or 30
                )
                send_message(client_sock, self.execute(command, timeout))
                return
            send_message(
                client_sock,
                {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Unknown action: {action}",
                },
            )
        except Exception as exc:
            try:
                send_message(
                    client_sock,
                    {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)},
                )
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
            "key": self.key,
            "hostname": self.connection.hostname,
            "port": self.connection.port,
            "username": self.connection.username,
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
                    _connection, self.ssh_client = connect_target(self.connection, timeout=timeout)
                except Exception as exc:
                    return {"success": False, "exit_code": -1, "stdout": "", "stderr": f"Reconnect failed: {exc}"}
            try:
                stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
                exit_code, stdout_text, stderr_text = read_exec_result(stdout, stderr, timeout=timeout)
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
                    _connection, self.ssh_client = connect_target(self.connection, timeout=30)
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
        daemon_info_path(self.key, self.root).unlink(missing_ok=True)


def daemon_status(connection: ConnectionConfig, *, root: Path) -> dict[str, Any]:
    key = daemon_key_for_connection(connection)
    info = read_daemon_info(key, root)
    if not info:
        return {
            "status": "not_running",
            "key": key,
            "hostname": connection.hostname,
            "port": connection.port,
            "username": connection.username,
        }
    try:
        payload = request_daemon(info, {"action": "ping"}, timeout=5)
        payload["key"] = key
        return payload
    except Exception as exc:
        daemon_info_path(key, root).unlink(missing_ok=True)
        return {
            "status": "unreachable",
            "key": key,
            "hostname": connection.hostname,
            "port": connection.port,
            "username": connection.username,
            "error": str(exc),
        }


def daemon_stop(connection: ConnectionConfig, *, root: Path) -> dict[str, Any]:
    key = daemon_key_for_connection(connection)
    info = read_daemon_info(key, root)
    if not info:
        return {
            "status": "not_running",
            "key": key,
            "hostname": connection.hostname,
            "port": connection.port,
            "username": connection.username,
        }
    try:
        payload = request_daemon(info, {"action": "shutdown"}, timeout=5)
        for _ in range(20):
            if not read_daemon_info(key, root):
                break
            time.sleep(0.05)
        daemon_info_path(key, root).unlink(missing_ok=True)
        return {
            **payload,
            "status": "stopped",
            "key": key,
            "hostname": connection.hostname,
            "port": connection.port,
            "username": connection.username,
        }
    except Exception as exc:
        daemon_info_path(key, root).unlink(missing_ok=True)
        return {
            "status": "force_cleaned",
            "key": key,
            "hostname": connection.hostname,
            "port": connection.port,
            "username": connection.username,
            "error": str(exc),
        }


def sftp_connect(
    connection: ConnectionConfig,
    *,
    timeout: int,
    root: Path,
    save_name: str | None = None,
):
    client = connect_client(connection, timeout=timeout)
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
    root: Path,
    recursive: bool,
    no_progress: bool,
    save_name: str | None = None,
) -> dict[str, Any]:
    if not local_path.exists():
        raise SSHSkillError(f"Local path not found: {local_path}")
    client, sftp = sftp_connect(
        connection,
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
    root: Path,
    recursive: bool,
    no_progress: bool,
    save_name: str | None = None,
) -> dict[str, Any]:
    client, sftp = sftp_connect(
        connection,
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
        client = connect_client(connection, timeout=connect_timeout)
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
    identity_file = getattr(args, "identity_file", None)
    return ConnectionOptions(
        username=getattr(args, "username", None),
        password=getattr(args, "password", None),
        identity_file=str(identity_file) if identity_file is not None else None,
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
            raise SSHSkillError("--password-stdin has been removed; use --password or a saved profile")
        if part == "--identity-file":
            options.identity_file, index = _value_after_option(command_parts, index, part)
            continue
        if part.startswith("--identity-file="):
            options.identity_file = part.split("=", 1)[1]
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
        int(validate_positive_int(timeout, "--timeout") or 30),
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
            raise SSHSkillError("--password-stdin has been removed; use --password or a saved profile")
        if part == "--identity-file":
            args.identity_file, index = _value_after_option(local_parts, index, part)
            continue
        if part.startswith("--identity-file="):
            args.identity_file = part.split("=", 1)[1]
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
    parser.add_argument("--identity-file", help="Private key file path")
    parser.add_argument("--port", type=int, help="SSH port")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the successfully authenticated connection as a project profile",
    )
    parser.add_argument("--save-as", help="Project profile name; requires --save")


def add_interactive_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username", help="SSH username")
    parser.add_argument(
        "--password",
        help="SSH password (may be exposed in shell history and process listings)",
    )
    parser.add_argument("--identity-file", help="Private key file path")
    parser.add_argument("--port", type=int, help="SSH port")


def add_control_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username", help="SSH username for direct daemon lookup")
    parser.add_argument("--port", type=int, help="SSH port")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSH skill CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root for daemon state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List saved SSH profiles")

    find_parser = subparsers.add_parser("find", help="Find saved SSH profiles")
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

    profiles_parser = subparsers.add_parser(
        "profiles",
        help="List or remove saved SSH profiles",
    )
    profiles_parser.add_argument("action", choices=["list", "remove"])
    profiles_parser.add_argument("name", nargs="?")

    control_parser = subparsers.add_parser("control", help="Manage the daemon")
    control_parser.add_argument("action", choices=["status", "stop"])
    control_parser.add_argument("target")
    add_control_identity_arguments(control_parser)

    daemon_parser = subparsers.add_parser("daemon", help=argparse.SUPPRESS)
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    start_parser = daemon_subparsers.add_parser("start")
    start_parser.add_argument("--start-file", type=Path, required=True)
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
    root = Path(args.root).resolve()
    secret_values: set[str] = set()

    try:
        try:
            secret_values.update(
                profile.password for profile in load_project_profiles(root).values() if profile.password
            )
        except SSHSkillError:
            pass
        if args.command == "list":
            json_print(
                {
                    "success": True,
                    "operation": "list",
                    "targets": list_targets(root=root),
                }
            )
            return 0
        if args.command == "find":
            json_print(
                {
                    "success": True,
                    "operation": "find",
                    "keyword": args.keyword,
                    "targets": find_targets(args.keyword, root=root),
                }
            )
            return 0
        if args.command == "profiles":
            if args.action == "list":
                if args.name is not None:
                    raise SSHSkillError("profiles list does not accept a profile name")
                json_print(
                    {
                        "success": True,
                        "operation": "profiles_list",
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
                raise SSHSkillError("profiles remove requires a profile name")
            result = remove_project_profile(args.name, root=root)
            result["operation"] = "profiles_remove"
            json_print(result)
            return 0 if result["removed"] else 1
        if args.command == "test":
            options = prepare_connection_options(_connection_options_from_args(args))
            if options.password:
                secret_values.add(options.password)
            connection = resolve_connection(
                args.target,
                root=root,
                options=options,
                require_auth=True,
            )
            if connection.password:
                secret_values.add(connection.password)
            validate_connection_auth_files(connection)
            ensure_paramiko()
            timeout = int(validate_positive_int(args.timeout, "--timeout") or 30)
            client = connect_client(connection, timeout=timeout)
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
                root=root,
                options=options,
                require_auth=no_daemon,
            )
            if connection.password:
                secret_values.add(connection.password)
            result = None
            if no_daemon:
                validate_connection_auth_files(connection)
            if not no_daemon:
                result = try_daemon_execute(connection, command, root=root, timeout=timeout)
                if result is not None and options.save:
                    save_project_profile(options.save_as or args.target, connection, root=root, stop_daemons=False)
                if result is None:
                    if not connection.has_auth():
                        raise SSHSkillError(
                            f"No matching daemon for {connection.username}@{connection.hostname}:{connection.port}; "
                            "provide --password, --identity-file, or use a saved profile"
                        )
                    validate_connection_auth_files(connection)
                    ensure_paramiko()
                    if start_daemon_background(
                        connection,
                        root=root,
                        idle_timeout=IDLE_TIMEOUT_SECONDS,
                    ):
                        if options.save:
                            save_project_profile(
                                options.save_as or args.target,
                                connection,
                                root=root,
                                stop_daemons=False,
                            )
                        result = try_daemon_execute(connection, command, root=root, timeout=timeout)
            if result is None:
                if not connection.has_auth():
                    raise SSHSkillError(
                        f"No matching daemon for {connection.username}@{connection.hostname}:{connection.port}; "
                        "provide --password, --identity-file, or use a saved profile"
                    )
                validate_connection_auth_files(connection)
                ensure_paramiko()
                result = execute_direct(
                    connection,
                    command,
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
                root=root,
                options=options,
                require_auth=True,
            )
            if connection.password:
                secret_values.add(connection.password)
            validate_connection_auth_files(connection)
            ensure_paramiko()
            return run_interactive(
                connection,
                command=command,
                shell_mode=shell_mode,
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
                root=root,
                options=options,
                require_auth=True,
            )
            if connection.password:
                secret_values.add(connection.password)
            validate_connection_auth_files(connection)
            ensure_paramiko()
            result = upload_path(
                connection,
                args.local_path,
                args.remote_path,
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
                root=root,
                options=options,
                require_auth=True,
            )
            if connection.password:
                secret_values.add(connection.password)
            validate_connection_auth_files(connection)
            ensure_paramiko()
            result = download_path(
                connection,
                args.remote_path,
                args.local_path,
                root=root,
                recursive=args.recursive,
                no_progress=args.no_progress,
                save_name=(options.save_as or args.target) if options.save else None,
            )
            json_print(result)
            return 0
        if args.command == "control":
            connection = resolve_control_connection(
                args.target,
                root=root,
                username=args.username,
                port=args.port,
            )
            payload = daemon_status(connection, root=root) if args.action == "status" else daemon_stop(connection, root=root)
            payload["success"] = payload.get("status") != "unreachable"
            payload["operation"] = f"control_{args.action}"
            json_print(payload)
            return 0
        if args.command == "daemon" and args.daemon_command == "start":
            connection = read_daemon_start_file(args.start_file)
            if connection.password:
                secret_values.add(connection.password)
            validate_connection_auth_files(connection)
            ensure_paramiko()
            idle_timeout = int(validate_positive_int(args.idle_timeout, "--idle-timeout") or IDLE_TIMEOUT_SECONDS)
            daemon = SSHDaemon(connection, root=root, idle_timeout=idle_timeout)
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
