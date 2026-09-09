from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.common.model import Node

_ROOT = Path(__file__).resolve().parents[1]
_PROFILES = _ROOT / "profiles"

# Built-in defaults so the engine runs without PyYAML.
_DEFAULTS: dict[str, dict[str, Any]] = {
    "nginx": {
        "uri_normalize": True,
        "framing": "content_length_primary",
        "upstream_keepalive": "unknown",
    },
    "apache": {
        # Apache typically merges // and may decode %2f depending on AllowEncodedSlashes.
        "uri_normalize": True,
        "merge_slashes": True,
        "framing": "unknown",
        "upstream_keepalive": "unknown",
        "encoded_slash_handling": "decode_or_reject",
        "listen_addrs": [],
    },
}


def _parse_simple_yaml_behaviors(text: str) -> dict[str, Any]:
    """Tiny subset parser for profiles/*.yaml (no PyYAML required)."""
    behaviors: dict[str, Any] = {}
    in_behaviors = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.strip() == "behaviors:":
            in_behaviors = True
            continue
        if not in_behaviors:
            continue
        if not line.startswith(" ") and not line.startswith("\t"):
            in_behaviors = False
            continue
        if ":" not in line:
            continue
        key, val = line.strip().split(":", 1)
        key, val = key.strip(), val.strip()
        if not key:
            continue
        if val.lower() in ("true", "yes"):
            behaviors[key] = True
        elif val.lower() in ("false", "no"):
            behaviors[key] = False
        elif val == "":
            continue
        else:
            behaviors[key] = val.strip('"').strip("'")
    return behaviors


def load_profile(kind: str) -> dict[str, Any]:
    base = dict(_DEFAULTS.get(kind, {}))
    path = _PROFILES / f"{kind}-default.yaml"
    if path.is_file():
        try:
            parsed = _parse_simple_yaml_behaviors(path.read_text(encoding="utf-8"))
            base.update(parsed)
        except OSError:
            pass
    return {"kind": kind, "behaviors": base}


def infer_nginx_behaviors(root: Node) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keepalive = False
    for node in root.walk():
        if node.kind == "directive" and node.name == "keepalive":
            keepalive = True
        if node.kind == "directive" and node.name == "proxy_http_version":
            if node.args and node.args[0] == "1.1":
                out["proxy_http_version"] = "1.1"
    if keepalive:
        out["upstream_keepalive"] = True
    return out


def infer_apache_behaviors(root: Node) -> dict[str, Any]:
    """Extract Listen addresses for matching nginx proxy_pass targets."""
    addrs: list[str] = []
    for node in root.walk():
        if node.kind != "directive" or node.name.lower() != "listen" or not node.args:
            continue
        raw = node.args[0]
        # Listen 127.0.0.1:60080  |  Listen 80  |  Listen [::]:443
        if ":" in raw and not raw.startswith("["):
            addrs.append(raw)
        elif raw.isdigit():
            addrs.append(f"0.0.0.0:{raw}")
            addrs.append(f"127.0.0.1:{raw}")
        else:
            addrs.append(raw)
    out: dict[str, Any] = {}
    if addrs:
        out["listen_addrs"] = sorted(set(addrs))
    return out


def merge_behaviors(kind: str, root: Node | None = None) -> dict[str, Any]:
    base = dict(load_profile(kind).get("behaviors") or {})
    if root is None:
        return base
    if kind == "nginx":
        base.update(infer_nginx_behaviors(root))
    elif kind in ("apache", "httpd"):
        base.update(infer_apache_behaviors(root))
    return base
