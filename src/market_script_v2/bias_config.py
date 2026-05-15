from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class LeanDrawParams:
    draw_dom_delta_abs_min: float
    close_dispersion_max: float
    draw_prob_delta_min: float
    p_draw_close_min: float
    favored_prob_delta_max: float


@dataclass(frozen=True)
class GuardDrawParams:
    draw_prob_delta_min: float
    favored_prob_delta_max: float


@dataclass(frozen=True)
class TwoHeadsParams:
    draw_prob_delta_max: float
    p_draw_close_max: float


@dataclass(frozen=True)
class V2PredictionBiasParams:
    lean_draw: LeanDrawParams
    guard_draw: GuardDrawParams
    two_heads: TwoHeadsParams


def _default_path() -> Path:
    return Path("data") / "rules" / "v2_prediction_bias_config.json"


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base or {})
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out.get(k) or {}, v)
        else:
            out[k] = v
    return out


def _match_override(match: Dict[str, Any], league: str, dispersion_close: Optional[float]) -> bool:
    match = match or {}
    league = str(league or "")
    contains = match.get("league_contains") or []
    if contains:
        if not any(str(x) and str(x) in league for x in contains):
            return False

    if dispersion_close is None:
        return True

    dmax = match.get("dispersion_close_max")
    if dmax is not None:
        try:
            if float(dispersion_close) > float(dmax):
                return False
        except Exception:
            return False

    dmin = match.get("dispersion_close_min")
    if dmin is not None:
        try:
            if float(dispersion_close) < float(dmin):
                return False
        except Exception:
            return False

    return True


def load_v2_prediction_bias_params(
    *,
    league: str,
    dispersion_close: Optional[float],
    path: Optional[str] = None,
) -> V2PredictionBiasParams:
    cfg_path = Path(path) if path else Path(os.getenv("V2_PREDICTION_BIAS_CONFIG") or "")
    if not cfg_path or str(cfg_path) in {".", ""}:
        cfg_path = _default_path()

    raw: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

    defaults = dict(raw.get("defaults") or {})
    merged = dict(defaults)
    for item in (raw.get("overrides") or []):
        if not isinstance(item, dict):
            continue
        if _match_override(item.get("match") or {}, league, dispersion_close):
            merged = _deep_merge(merged, dict(item.get("params") or {}))

    lean = dict(merged.get("lean_draw") or {})
    guard = dict(merged.get("guard_draw") or {})
    two = dict(merged.get("two_heads") or {})

    return V2PredictionBiasParams(
        lean_draw=LeanDrawParams(
            draw_dom_delta_abs_min=float(lean.get("draw_dom_delta_abs_min") or 0.02),
            close_dispersion_max=float(lean.get("close_dispersion_max") or 0.08),
            draw_prob_delta_min=float(lean.get("draw_prob_delta_min") or 0.015),
            p_draw_close_min=float(lean.get("p_draw_close_min") or 0.28),
            favored_prob_delta_max=float(lean.get("favored_prob_delta_max") or 0.0),
        ),
        guard_draw=GuardDrawParams(
            draw_prob_delta_min=float(guard.get("draw_prob_delta_min") or 0.01),
            favored_prob_delta_max=float(guard.get("favored_prob_delta_max") or -0.01),
        ),
        two_heads=TwoHeadsParams(
            draw_prob_delta_max=float(two.get("draw_prob_delta_max") or -0.01),
            p_draw_close_max=float(two.get("p_draw_close_max") or 0.23),
        ),
    )

