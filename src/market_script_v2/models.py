from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class MarketScriptV2Output:
    fixture_id: str
    prediction_period: str
    league: str
    mode: str
    engine_version: str
    prototype: str
    subclass: str
    action_type: str
    strength: str
    prediction_bias: str
    direction_hint: str
    why: str
    veto_tags: list[str]
    signal_bucket: str
    clv_prob: float | None
    clv_logit: float | None
    dispersion: float | None
    nspf_top1: str = ""
    nspf_cover: str = ""
    nspf_confidence: int | None = None
    nspf_scores: dict[str, float] | None = None
    decision_reason: str = ""
    feedback_tag: str = ""
    upset_alert_level: str = ""
    upset_alert_score: int | None = None
    upset_direction: str = ""
    upset_reasons: list[str] = field(default_factory=list)
    upset_guard_pick: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_record(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "prediction_period": self.prediction_period,
            "league": self.league,
            "mode": self.mode,
            "engine_version": self.engine_version,
            "prototype": self.prototype,
            "subclass": self.subclass,
            "action_type": self.action_type,
            "strength": self.strength,
            "prediction_bias": self.prediction_bias,
            "direction_hint": self.direction_hint,
            "why": self.why,
            "veto_tags": self.veto_tags,
            "signal_bucket": self.signal_bucket,
            "clv_prob": self.clv_prob,
            "clv_logit": self.clv_logit,
            "dispersion": self.dispersion,
            "nspf_top1": self.nspf_top1,
            "nspf_cover": self.nspf_cover,
            "nspf_confidence": self.nspf_confidence,
            "nspf_scores": self.nspf_scores,
            "decision_reason": self.decision_reason,
            "feedback_tag": self.feedback_tag,
            "upset_alert_level": self.upset_alert_level,
            "upset_alert_score": self.upset_alert_score,
            "upset_direction": self.upset_direction,
            "upset_reasons": self.upset_reasons,
            "upset_guard_pick": self.upset_guard_pick,
            "created_at": self.created_at,
        }


def build_v2_rule_id(subclass: str) -> str:
    safe = "".join([ch if (ch.isalnum() or ch == "_") else "_" for ch in (subclass or "")])
    safe = safe.strip("_")
    if not safe:
        safe = "v2_unknown"
    if not safe.startswith("v2_"):
        safe = f"v2_{safe}"
    return safe


def format_v2_lines(output: MarketScriptV2Output) -> list[str]:
    rid = build_v2_rule_id(output.subclass)
    head = f"{output.prototype}/{output.subclass}"
    base = f"[{rid}] {head}：{output.action_type}/{output.strength}"
    parts = [base]
    if output.prediction_bias:
        parts.append(f"[{rid}] prediction_bias：{output.prediction_bias}")
    if output.nspf_top1:
        parts.append(f"[{rid}] nspf_top1：{output.nspf_top1}")
    if output.nspf_cover:
        parts.append(f"[{rid}] nspf_cover：{output.nspf_cover}")
    if output.nspf_confidence is not None:
        parts.append(f"[{rid}] nspf_confidence：{output.nspf_confidence}")
    if output.direction_hint:
        parts.append(f"[{rid}] direction_hint：{output.direction_hint}")
    if output.upset_alert_level:
        parts.append(f"[{rid}] upset_alert：{output.upset_alert_level}/{output.upset_alert_score}")
    if output.upset_guard_pick:
        parts.append(f"[{rid}] upset_guard_pick：{output.upset_guard_pick}")
    if output.why:
        parts.append(f"[{rid}] why：{output.why}")
    if output.decision_reason:
        parts.append(f"[{rid}] decision_reason：{output.decision_reason}")
    if output.veto_tags:
        parts.append(f"[{rid}] veto：{','.join(output.veto_tags)}")
    return parts


def v2_triggered_rule_ids(output: Optional[MarketScriptV2Output]) -> list[str]:
    if not output:
        return []
    if (output.action_type or "").lower() == "diagnosis":
        return []
    return [build_v2_rule_id(output.subclass)]
