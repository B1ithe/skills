# engine/

Generic **config-defect rule engine** (not CRLF-specific):

**Analyzers → Signals → Evaluators → Findings**, plus `chain/` for multi-hop.

## Nginx rule packs (gixy parity)

| Pack | Finding id prefix | Notes |
|------|-------------------|-------|
| http_splitting | `nginx.http_splitting.*` | `$uri` / unsafe captures → sinks |
| host_spoofing | `nginx.host_spoofing.*` | `Host $http_host` / `$arg_*` |
| ssrf | `nginx.ssrf.*` | controllable `proxy_pass` authority |
| origins | `nginx.origins.*` | weak Referer/Origin regex |
| add_header_redefinition | `nginx.add_header_redefinition.*` | nested `add_header` drops parents |
| add_header_multiline | `nginx.add_header_multiline.*` | folded header values |
| valid_referers | `nginx.valid_referers.*` | `none` in valid_referers |
| alias_traversal | `nginx.alias_traversal.*` | alias + prefix location w/o `/` |

Parity suite: `fixtures/gixy-simply/` + `scripts/test_gixy_parity.py`.

## Chain rules

| Pack | Finding id | Requires |
|------|------------|----------|
| path_confusion | `chain.path_confusion.nginx_apache_decode_normalize` | nginx `proxy_pass` to Apache (Listen matched). Finding carries `affected_versions` (nginx `*`; apache `<2.4.49` vs `>=2.4.49`). |

Findings may include optional `affected_versions`: `[{component, versions, note}, ...]`.
The engine **emits** ranges only — it does not probe installed binaries or suppress
findings by version. The agent correlates `affected_versions` with the real
deployment version when reporting.
