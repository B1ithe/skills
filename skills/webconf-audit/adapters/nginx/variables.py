from __future__ import annotations

"""Nginx variable primitives (gixy-like character-set model).

Used by engine analyzers to decide whether a script like
`http://backend$uri` may introduce CR/LF into upstream bytes.
"""

import re
from dataclasses import dataclass, field

# Capture $name, ${name}, and $1..$9
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([1-9])|\$([A-Za-z_][A-Za-z0-9_]*)")

# Builtin models aligned with gixy intent (approximate nginx semantics).
# True  => may contain the char
# False => must not contain the char under normal parsing
# None  => unknown / treat as not user-controlled for CRLF purposes
_BUILTIN_NL: dict[str, bool | None] = {
    # Decoded / normalized path — %0d%0a becomes real newlines
    "uri": True,
    "document_uri": True,
    # Original request target — stays percent-encoded
    "request_uri": False,
    "is_args": False,
    "args": False,
    "query_string": False,
    "host": False,
    "hostname": False,
    "remote_addr": False,
    "proxy_protocol_addr": False,
    "proxy_add_x_forwarded_for": False,
    "scheme": False,
    "request_method": False,
    "server_name": False,
    "request_id": False,
}


@dataclass
class VarRef:
    name: str  # without '$'
    raw: str  # as appeared, e.g. $uri or ${uri}


@dataclass
class NginxVarModel:
    """Resolve whether named vars / scripts may contain newlines."""

    # Captures from location/rewrite regex: name -> may_contain_newline
    captures: dict[str, bool] = field(default_factory=dict)
    # set $name ... assignments: name -> depends on other names
    assignments: dict[str, list[str]] = field(default_factory=dict)

    def may_contain_newline(self, name: str) -> bool:
        name = name.lstrip("$")
        if name in self.captures:
            return self.captures[name]
        if name.startswith("arg_"):
            return False
        if name.startswith("http_") or name.startswith("cookie_") or name.startswith("sent_http_"):
            return False
        if name.startswith("upstream_http_"):
            return False
        if name in _BUILTIN_NL:
            flag = _BUILTIN_NL[name]
            return bool(flag)
        if name in self.assignments:
            return any(self.may_contain_newline(dep) for dep in self.assignments[name])
        # Indexed captures $1..$9 without known regexp → conservative False
        # (unknown user control; prefer not to flood FPs). Analyzers that know
        # the location regexp should register captures explicitly.
        if name.isdigit():
            return self.captures.get(name, False)
        return False

    def script_may_contain_newline(self, script: str) -> bool:
        return any(self.may_contain_newline(v.name) for v in extract_vars(script))

    def dangerous_vars_in_script(self, script: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for v in extract_vars(script):
            if v.name not in seen and self.may_contain_newline(v.name):
                seen.add(v.name)
                out.append(v.name)
        return out


def extract_vars(script: str) -> list[VarRef]:
    refs: list[VarRef] = []
    for m in _VAR_RE.finditer(script or ""):
        name = m.group(1) or m.group(2) or m.group(3)
        refs.append(VarRef(name=name, raw=m.group(0)))
    return refs


_CHARCLASS_RE = re.compile(r"\[(\^?)(.*?)\]")


def capture_may_contain_newline(pattern: str, group_name: str | int | None = None) -> bool:
    """Heuristic: exclusive classes like [^/] can include \\n; '.' usually cannot."""
    # Very small subset — enough for common location ~ patterns.
    # If ^ is used with a class that does not exclude \n, treat as dangerous.
    for m in _CHARCLASS_RE.finditer(pattern):
        neg, body = m.group(1), m.group(2)
        if not neg:
            # Positive class including \n or \x0a
            if "\\n" in body or "\\x0a" in body.lower() or "\n" in body:
                return True
            continue
        # Negated class: dangerous unless it excludes newline-ish
        # [^/] [^.] [^\s] — \s excludes newline; / and . do not
        if "\\s" in body or "\\n" in body or "\\x0a" in body.lower():
            continue
        return True
    # Bare "." does not match newline in default nginx/PCRE
    return False


def build_var_model_from_ast(root) -> NginxVarModel:
    """Collect set assignments and location capture hints from AST."""
    model = NginxVarModel()
    for node in root.walk():
        if node.kind == "directive" and node.name == "set" and len(node.args) >= 2:
            # set $a $b$c;
            target = node.args[0].lstrip("$")
            deps = [v.name for v in extract_vars(" ".join(node.args[1:]))]
            model.assignments[target] = deps
        if node.kind == "block" and node.name == "location":
            # location ~ pattern { ... }  or  location ~* pattern
            args = node.args
            if len(args) >= 2 and args[0] in ("~", "~*"):
                pattern = args[1]
                # named groups
                for nm in re.findall(r"\(\?<(\w+)>", pattern):
                    model.captures[nm] = capture_may_contain_newline(pattern, nm)
                # numbered groups: mark all as same heuristic if exclusive class present
                if capture_may_contain_newline(pattern):
                    for i in range(1, 10):
                        model.captures.setdefault(str(i), True)
    return model
