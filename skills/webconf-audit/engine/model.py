from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    file: str | None = None
    line: int | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.file:
            d["file"] = self.file
        if self.line is not None:
            d["line"] = self.line
        if self.snippet:
            d["snippet"] = self.snippet
        return d


@dataclass
class Signal:
    id: str
    hop_id: str
    issuer: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "hop_id": self.hop_id,
            "issuer": self.issuer,
            "evidence": [e.to_dict() for e in self.evidence],
            "data": self.data,
            "confidence": self.confidence,
        }


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    category: str = "single_hop"  # single_hop | chain
    hop_ids: list[str] = field(default_factory=list)
    based_on: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    remediation: str | None = None
    confidence: str = "high"
    summary: str | None = None
    # Version coverage for version-scoped defects, e.g.
    # [{"component": "apache", "versions": ">=2.4.49", "note": "..."}]
    affected_versions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "category": self.category,
            "hop_ids": self.hop_ids,
            "based_on": self.based_on,
            "evidence": [e.to_dict() for e in self.evidence],
            "remediation": self.remediation,
            "confidence": self.confidence,
            "summary": self.summary,
        }
        if self.affected_versions:
            d["affected_versions"] = [dict(x) for x in self.affected_versions]
        return d


@dataclass
class Hop:
    id: str
    kind: str
    role: str = "edge"
    entry_file: str | None = None


@dataclass
class HopResult:
    hop: Hop
    signals: list[Signal] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    behaviors: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def has_signal(self, signal_id: str) -> bool:
        return any(s.id == signal_id for s in self.signals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hop": {
                "id": self.hop.id,
                "kind": self.hop.kind,
                "role": self.hop.role,
                "entry_file": self.hop.entry_file,
            },
            "signals": [s.to_dict() for s in self.signals],
            "findings": [f.to_dict() for f in self.findings],
            "behaviors": self.behaviors,
            "warnings": self.warnings,
        }


@dataclass
class PipelineResult:
    hops: list[HopResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)  # chain-only

    def all_findings(self) -> list[Finding]:
        """Chain findings + each hop's single-hop findings."""
        out = list(self.findings)
        for h in self.hops:
            out.extend(h.findings)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "hops": [h.to_dict() for h in self.hops],
            "findings": [f.to_dict() for f in self.findings],  # chain-only
            "all_findings": [f.to_dict() for f in self.all_findings()],
        }
