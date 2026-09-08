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
        "uri_normalize": True,
        "framing": "unknown",
        "upstream_keepalive": "unknown",
        "encoded_slash_handling": "unknown",
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


def merge_behaviors(kind: str, root: Node | None = None) -> dict[str, Any]:
    base = dict(load_profile(kind).get("behaviors") or {})
    if kind == "nginx" and root is not None:
        base.update(infer_nginx_behaviors(root))
    return base
