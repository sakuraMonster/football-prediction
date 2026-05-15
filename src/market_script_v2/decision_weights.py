from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _default_path() -> Path:
    return Path("data") / "rules" / "v2_decision_weights.json"


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base or {})
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out.get(k) or {}, v)
        else:
            out[k] = v
    return out


def _match_override(match: Dict[str, Any], league: str, dispersion: Optional[float]) -> bool:
    match = match or {}
    league = str(league or "")
    contains = match.get("league_contains") or []
    if contains and not any(str(item) and str(item) in league for item in contains):
        return False

    if dispersion is None:
        return True

    dmax = match.get("dispersion_max")
    if dmax is not None:
        try:
            if float(dispersion) > float(dmax):
                return False
        except Exception:
            return False

    dmin = match.get("dispersion_min")
    if dmin is not None:
        try:
            if float(dispersion) < float(dmin):
                return False
        except Exception:
            return False

    return True


def load_v2_decision_weights(
    *,
    league: str,
    dispersion: Optional[float],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    cfg_path = Path(path) if path else Path(os.getenv("V2_DECISION_WEIGHTS_CONFIG") or "")
    if not cfg_path or str(cfg_path) in {".", ""}:
        cfg_path = _default_path()

    raw: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

    merged = dict(raw.get("defaults") or {})
    for item in (raw.get("overrides") or []):
        if not isinstance(item, dict):
            continue
        if _match_override(item.get("match") or {}, league, dispersion):
            merged = _deep_merge(merged, dict(item.get("weights") or {}))
    return merged
