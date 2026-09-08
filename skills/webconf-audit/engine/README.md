# engine/

Generic **config-defect rule engine** (not CRLF-specific):

**Analyzers → Signals → Evaluators → Findings**, plus `chain/` for multi-hop.

Rule packs live as analyzers/evaluators/chain modules (http_splitting, host_trust,
path confusion, …). Adding a vulnerability class = adding a pack, not changing the runner.

- `model.py` — Signal / Finding / HopResult / PipelineResult
- `runner.py` — `audit_nginx_file`, `audit_pipeline`
- `analyzers/<server>/` — emit Signals
- `evaluators/<server>/` — Signals → Findings
- `chain/` — cross-hop Findings
