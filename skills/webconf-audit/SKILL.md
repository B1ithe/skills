---
name: webconf-audit
description: >
  Audit nginx/apache configs for defective security settings via self-built parsers and a
  rule engine (not CRLF-only: splitting, host trust, path confusion, risky proxy, etc.).
  Supports single-hop findings and future nginx→apache chain rules. Triggers: /webconf-audit,
  "解析 nginx 配置", "审计 nginx 配置", "配置缺陷扫描", "nginx apache 组合".
---

# webconf-audit

## Positioning

**Preconfigured-rule config defect scanner** for web servers — not a CRLF-only tool.
CRLF/`$uri`, Host trust, path decode/normalize confusion, etc. are all **rule packs**
on the same engine.

## Current scope

- **Parsers**: nginx + apache → JSON AST
- **Engine (nginx)**: variables + analyzers/evaluators → Signals/Findings  
  (**gixy parity**: `http_splitting`, `host_spoofing`, `ssrf`, `origins`,
  `add_header_redefinition`, `add_header_multiline`, `valid_referers`,
  `alias_traversal`)
- **Chain**: `path_confusion` (nginx HTTP reverse-proxy → Apache decode/normalize
  order mismatch) — run only for upstreams that are resolved (see Orchestration)

See `references/design.md`.

## Parse

```bash
python scripts/parse_config.py nginx fixtures/nginx/minimal.conf --pretty
python scripts/parse_config.py apache fixtures/apache/minimal.conf --pretty
python scripts/parse_config.py nginx /path/to/nginx.conf \
  --path-map /usr/local/nginx/conf=/path/to/local/conf --pretty
```

## Audit (nginx)

```bash
python scripts/audit.py nginx fixtures/nginx/minimal.conf --pretty
python scripts/audit.py nginx fixtures/nginx/safe_request_uri.conf --pretty
python scripts/audit.py nginx /path/to/nginx.conf \
  --path-map /usr/local/nginx/conf=/path/to/local/conf --pretty

# Multi-hop (different kinds): kind-keyed maps are fine
python scripts/audit.py pipeline \
  --hop nginx:/path/to/nginx.conf \
  --hop apache:/path/to/httpd.conf \
  --hop-path-map nginx:/usr/local/nginx/conf=/path/to/nginx/conf \
  --hop-path-map apache:conf=/path/to/apache \
  --pretty

# Two nginx hops (front/back): give each hop an id and key maps by id
python scripts/audit.py pipeline \
  --hop front=nginx:/front/nginx.conf \
  --hop back=nginx:/back/nginx.conf \
  --hop-path-map front:/usr/local/nginx/conf=/local/front/conf \
  --hop-path-map back:/etc/nginx=/local/back/conf \
  --pretty
```

## Orchestration

1. Identify the edge server + entry file (+ path-map).
2. Always run **single-hop** audit on every available conf first (`audit.py` /
   `parse_config.py`). Report code findings with evidence; do not drop
   high-confidence hits.
3. **Multi-upstream / chain** (edge may fan out to several backends):
   - From the edge AST, list candidate **HTTP** upstreams (`proxy_pass` under
     `http`/`server`/`location` — ignore `stream` proxies). One edge hop + N
     origin hops; chain rules run **per resolved edge→origin route**.
   - If the agent can resolve an upstream (conf path + kind: nginx/apache/…,
     locally or from context) → audit that hop and run chain rules for that
     route. Use `--hop-path-map KEY:SRC=DST` where KEY is hop **id**, hop
     **index**, or kind. For **two nginx hops**, assign ids
     (`--hop front=nginx:...`) and map by id — kind-only maps are not enough.
   - If it cannot resolve an upstream → **ask the user** for that upstream’s
     conf (and server kind), **unless** the user already scoped the audit to a
     subset of upstreams (then SKIP the rest without asking). Do not guess
     missing configs.
   - If the user declines or cannot provide it → **skip chain analysis for that
     route only**; still keep edge single-hop findings. Say clearly which
     routes were skipped and why.
4. **Version-scoped findings**: the engine may attach `affected_versions`
   (component + version range + note). It does **not** detect or filter by the
   live binary version from conf alone. The agent should:
   - surface those ranges in the report;
   - resolve the real version from context / ask the user if needed;
   - judge applicability (e.g. Apache `<2.4.49` vs `>=2.4.49`) and say whether
     the finding is relevant, reduced, or N/A for this deployment.
5. An LLM may explain findings; must not invent chain issues for unresolved
   routes; must not drop high-confidence code hits solely because version is
   unknown — mark version as unverified instead.

## Smoke / corpus (AST)

```bash
python scripts/smoke_test.py
python scripts/test_parser_ast.py
python scripts/test_gixy_parity.py
python scripts/corpus_validate.py
# optional: rebuild fixtures/corpus from /tmp/webconf-corpus + /tmp/webconf-repos
python scripts/corpus_rebuild.py && python scripts/corpus_validate.py
```

Corpus configs live under `fixtures/corpus/{nginx,apache}/` (real GitHub projects,
lightly sanitized templates). Validation checks parse + basic AST structure.

## Later

- More apache single-hop analyzers
- Optional LLM pass + bundle schema
- Additional chain packs beyond path_confusion
