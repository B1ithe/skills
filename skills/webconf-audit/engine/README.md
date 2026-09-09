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
