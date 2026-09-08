from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.base import get_adapter
from engine.behaviors import merge_behaviors
from engine.model import Hop, HopResult, PipelineResult


def audit_nginx_file(
    path: str | Path,
    *,
    hop_id: str = "nginx-0",
    path_map: dict[str, str] | None = None,
) -> HopResult:
    from engine.analyzers import nginx as nginx_analyzers
    from engine.evaluators import nginx as nginx_evaluators

    path = Path(path)
    parsed = get_adapter("nginx").parse_file(path, path_map=path_map)
    root = parsed.document.root
    hop = Hop(id=hop_id, kind="nginx", role="edge", entry_file=str(path.resolve()))
    signals = nginx_analyzers.run_all(root, hop_id=hop_id)
    findings = nginx_evaluators.run_all(signals, hop_id=hop_id)
    behaviors = merge_behaviors("nginx", root)
    return HopResult(
        hop=hop,
        signals=signals,
        findings=findings,
        behaviors=behaviors,
        warnings=list(parsed.warnings),
    )


def audit_apache_file(
    path: str | Path,
    *,
    hop_id: str = "apache-0",
    path_map: dict[str, str] | None = None,
) -> HopResult:
    # Analyzers/evaluators for apache come later; still return parse + profile.
    path = Path(path)
    parsed = get_adapter("apache").parse_file(path, path_map=path_map)
    hop = Hop(id=hop_id, kind="apache", role="origin", entry_file=str(path.resolve()))
    return HopResult(
        hop=hop,
        signals=[],
        findings=[],
        behaviors=merge_behaviors("apache", parsed.document.root),
        warnings=list(parsed.warnings),
    )


def audit_pipeline(hops: list[dict[str, Any]]) -> PipelineResult:
    """Run per-hop audits then chain evaluators.

    hops item: {kind, path, hop_id?, path_map?, role?}
    """
    from engine.chain import run_all as run_chain

    results: list[HopResult] = []
    for i, spec in enumerate(hops):
        kind = spec["kind"]
        path = spec["path"]
        hop_id = spec.get("hop_id") or f"{kind}-{i}"
        path_map = spec.get("path_map")
        if kind == "nginx":
            hr = audit_nginx_file(path, hop_id=hop_id, path_map=path_map)
        elif kind in ("apache", "httpd"):
            hr = audit_apache_file(path, hop_id=hop_id, path_map=path_map)
        else:
            raise ValueError(f"unsupported hop kind: {kind}")
        if spec.get("role"):
            hr.hop.role = spec["role"]
        results.append(hr)

    chain_findings = run_chain(results)
    return PipelineResult(hops=results, findings=chain_findings)
