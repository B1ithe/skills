# Architecture (summary)

Full design: [design.md](design.md)

- **adapters/** — parse only (+ nginx variable primitives later)
- **engine/** — analyzers → signals → evaluators → findings; chain for multi-hop
- **scripts/** — thin CLI only
- **Signal** = former “facts”, owned by the rule engine (not adapters)
- Signal ids are semantic by default; `nginx.*` / `apache.*` only for private observations
- Missing signal on a hop means “not observed”, not an error (asymmetric OK for nginx→apache)
