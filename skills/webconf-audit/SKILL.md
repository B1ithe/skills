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
- **Chain**: stub (e.g. prefix `proxy_pass` + Apache path confusion — next)

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
```

## Orchestration

1. Identify server + entry file (+ path-map)
2. Prefer `audit.py` for nginx security output; use `parse_config.py` for AST-only
3. Report code findings with evidence; do not invent chain issues yet
4. An LLM may explain findings; must not drop high-confidence code hits

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

- Full chain evaluators (nginx→apache)
- More apache analyzers
- Optional LLM pass + bundle schema
