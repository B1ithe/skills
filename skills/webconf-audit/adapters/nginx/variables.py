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

# For SSRF: whether a var can introduce '.' in a host/scheme position,
# and whether it *must* contain '/' (path-like → skip host checks).
_BUILTIN_DOT: dict[str, bool] = {
    "uri": True,
    "document_uri": True,
    "request_uri": True,
    "host": True,
    "http_host": True,
    "hostname": False,
    "scheme": False,
    "request_method": False,
    "remote_addr": True,
    "args": True,
    "query_string": True,
}
_BUILTIN_MUST_SLASH: dict[str, bool] = {
    "uri": True,
    "document_uri": True,
    "request_uri": True,
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

    def can_contain(self, name: str, char: str) -> bool:
        """Rough gixy-like can_contain for SSRF / injection checks."""
        name = name.lstrip("$")
        if char in ("\n", "\r"):
            return self.may_contain_newline(name)
        if char == ".":
            if name.startswith("arg_") or name.startswith("http_") or name.startswith("cookie_"):
                return True
            if name in self.captures:
                # Exclusive-class captures typically allow '.'
                return True
            if name.isdigit():
                return self.captures.get(name, False)
            if name in self.assignments:
                return any(self.can_contain(dep, ".") for dep in self.assignments[name])
            return _BUILTIN_DOT.get(name, False)
        return False

    def must_contain(self, name: str, char: str) -> bool:
        name = name.lstrip("$")
        if char == "/":
            if name in self.assignments:
                return any(self.must_contain(dep, "/") for dep in self.assignments[name])
            return _BUILTIN_MUST_SLASH.get(name, False)
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
    """Heuristic: exclusive classes like [^/] / \\W can include \\n; '.' usually cannot."""
    # \\W = non-word = includes newline; \\D = non-digit = includes newline.
    # \\S = non-space = excludes newline.
    if re.search(r"\\[WD]", pattern):
        return True
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
                bodies = capturing_group_bodies(pattern)
                for i, body in enumerate(bodies, 1):
                    model.captures[str(i)] = capture_may_contain_newline(body)
                # named groups (?<name>...) / (?P<name>...)
                for m in re.finditer(r"\(\?<(\w+)>|\(\?P<(\w+)>", pattern):
                    name = m.group(1) or m.group(2)
                    # body starts after the name marker — approximate with full pattern heuristic
                    model.captures[name] = capture_may_contain_newline(pattern)
                # Refine named group bodies when we can pair with bodies list
                for m in re.finditer(r"\(\?<(\w+)>([^)]*)\)|\(\?P<(\w+)>([^)]*)\)", pattern):
                    name = m.group(1) or m.group(3)
                    body = m.group(2) if m.group(1) else m.group(4)
                    if name and body is not None:
                        model.captures[name] = capture_may_contain_newline(body)
    return model


def capturing_group_bodies(pattern: str) -> list[str]:
    """Return inner text of each capturing group (skips (?:, (?=, etc.)."""
    bodies: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i] == "(" and (i == 0 or pattern[i - 1] != "\\"):
            # non-capturing / lookaround
            if pattern.startswith(("?:", "?=", "?!", "?<=", "?<!"), i + 1):
                i += 1
                continue
            # named or plain capturing
            j = i + 1
            if pattern.startswith("?<", j) or pattern.startswith("?P<", j):
                gt = pattern.find(">", j)
                j = gt + 1 if gt != -1 else j
            depth = 1
            k = j
            while k < n and depth:
                if pattern[k] == "(" and pattern[k - 1] != "\\":
                    depth += 1
                elif pattern[k] == ")" and pattern[k - 1] != "\\":
                    depth -= 1
                k += 1
            bodies.append(pattern[j : k - 1])
            i = k
            continue
        i += 1
    return bodies
