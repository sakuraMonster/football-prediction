from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.market_script_v2.config import V2SubclassConfig


@dataclass(frozen=True)
class MatchFeatures:
    prototype: str
    subclass: str
    favored_side: str
    euro_favored_prob_delta: float | None
    draw_prob_delta: float | None
    dispersion_open: float | None
    dispersion_close: float | None
    convergence_flag: bool
    who_moves_first: str
    velocity: str
    ah_line_cross: bool
    ah_price_swing: float | None
    reversal_flag: bool


def _get(features: MatchFeatures, key: str):
    mapping: Dict[str, Any] = {
        "favored_side": features.favored_side,
        "favored_prob_delta": features.euro_favored_prob_delta,
        "euro_favored_prob_delta": features.euro_favored_prob_delta,
        "draw_prob_delta": features.draw_prob_delta,
        "dispersion_open": features.dispersion_open,
        "dispersion_close": features.dispersion_close,
        "convergence_flag": features.convergence_flag,
        "who_moves_first": features.who_moves_first,
        "velocity": features.velocity,
        "ah_line_cross": features.ah_line_cross,
        "ah_price_swing": features.ah_price_swing,
        "reversal_flag": features.reversal_flag,
    }
    return mapping.get(key)


def match_detection(cfg: V2SubclassConfig, features: MatchFeatures) -> bool:
    det = cfg.detection or {}
    if not det:
        return False
    for k, v in det.items():
        if str(k) == "prototype":
            if str(features.prototype) != str(v):
                return False
            continue
        if str(k) == "subclass":
            if str(features.subclass) != str(v):
                return False
            continue
        if str(k) in {"min_bucket_count", "min_reversal_abs"}:
            continue
        if str(k) == "max_dispersion":
            if features.dispersion_open is None:
                return False
            if float(features.dispersion_open) > float(v):
                return False
            continue
        if str(k) == "dispersion_ge":
            if features.dispersion_open is None:
                return False
            if float(features.dispersion_open) < float(v):
                return False
            continue
        if str(k) == "dispersion_le":
            if features.dispersion_open is None:
                return False
            if float(features.dispersion_open) > float(v):
                return False
            continue
        if str(k) == "favored_side_required":
            if bool(v) and features.favored_side not in {"home", "away"}:
                return False
            continue
        actual = _get(features, str(k))

        if actual is None and str(k) in {"who_moves_first", "velocity"}:
            return False

        if k.endswith("_ge"):
            base = k[:-3]
            actual = _get(features, base)
            if actual is None:
                return False
            if float(actual) < float(v):
                return False
            continue
        if k.endswith("_le"):
            base = k[:-3]
            actual = _get(features, base)
            if actual is None:
                return False
            if float(actual) > float(v):
                return False
            continue

        if k == "favored_prob_delta_ge":
            actual = features.euro_favored_prob_delta
            if actual is None or float(actual) < float(v):
                return False
            continue
        if k == "favored_prob_delta_le":
            actual = features.euro_favored_prob_delta
            if actual is None or float(actual) > float(v):
                return False
            continue
        if k == "euro_favored_prob_delta_le":
            actual = features.euro_favored_prob_delta
            if actual is None or float(actual) > float(v):
                return False
            continue
        if k == "draw_prob_delta_ge":
            actual = features.draw_prob_delta
            if actual is None or float(actual) < float(v):
                return False
            continue
        if k == "ah_price_swing_ge":
            actual = features.ah_price_swing
            if actual is None or float(actual) < float(v):
                return False
            continue

        if isinstance(v, bool):
            if bool(actual) != bool(v):
                return False
            continue

        if isinstance(v, (int, float)):
            if actual is None:
                return False
            if float(actual) != float(v):
                return False
            continue

        if isinstance(v, str):
            if str(actual) != v:
                return False
            continue

        if v is None:
            if actual is not None:
                return False
            continue

        return False

    return True


def select_best_subclass(
    subclasses: Dict[str, V2SubclassConfig],
    features: MatchFeatures,
) -> Optional[V2SubclassConfig]:
    matches = []
    for cfg in subclasses.values():
        if cfg.prototype and cfg.prototype != features.prototype:
            continue
        if match_detection(cfg, features):
            matches.append(cfg)

    if not matches:
        return None

    matches.sort(key=lambda c: (len(c.detection or {}), c.subclass_id), reverse=True)
    return matches[0]
