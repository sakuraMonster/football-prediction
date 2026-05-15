from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.market_script_v2.taxonomy import load_v2_taxonomy


@dataclass(frozen=True)
class V2MonitoringPolicy:
    status: str
    short_window: int
    mid_window: int
    alpha: float


@dataclass(frozen=True)
class V2SubclassConfig:
    subclass_id: str
    prototype: str
    default_action: str
    allow_direction: bool
    veto_tags: list[str]
    detection: dict[str, Any]
    monitoring: V2MonitoringPolicy


def _default_config_path() -> Path:
    return Path("data") / "rules" / "market_script_v2_subclasses.json"


def load_v2_subclass_configs(path: str | None = None) -> dict[str, V2SubclassConfig]:
    cfg_path = Path(path) if path else _default_config_path()
    if not cfg_path.exists():
        return {}
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    items = raw.get("subclasses") or []
    out: dict[str, V2SubclassConfig] = {}
    for item in items:
        monitoring_raw = item.get("monitoring") or {}
        monitoring = V2MonitoringPolicy(
            status=str(monitoring_raw.get("status") or "gray"),
            short_window=int(monitoring_raw.get("short_window") or 80),
            mid_window=int(monitoring_raw.get("mid_window") or 240),
            alpha=float(monitoring_raw.get("alpha") or 0.2),
        )
        cfg = V2SubclassConfig(
            subclass_id=str(item.get("subclass_id") or ""),
            prototype=str(item.get("prototype") or ""),
            default_action=str(item.get("default_action") or "Risk"),
            allow_direction=bool(item.get("allow_direction")),
            veto_tags=[str(x) for x in (item.get("veto_tags") or []) if str(x)],
            detection=dict(item.get("detection") or item.get("thresholds") or {}),
            monitoring=monitoring,
        )
        if cfg.subclass_id:
            out[cfg.subclass_id] = cfg
    return out


def validate_v2_configs(subclasses: dict[str, V2SubclassConfig]) -> list[str]:
    taxonomy = load_v2_taxonomy()
    warnings: list[str] = []

    for subclass_id, cfg in subclasses.items():
        if cfg.prototype and cfg.prototype not in taxonomy:
            warnings.append(f"unknown_prototype::{subclass_id}::{cfg.prototype}")
        if not cfg.prototype:
            warnings.append(f"missing_prototype::{subclass_id}")
        if cfg.default_action not in {"Direction", "Risk", "Diagnosis"}:
            warnings.append(f"invalid_default_action::{subclass_id}::{cfg.default_action}")
        if not isinstance(cfg.detection, dict):
            warnings.append(f"invalid_detection::{subclass_id}")
        if cfg.monitoring.short_window <= 0 or cfg.monitoring.mid_window <= 0:
            warnings.append(f"invalid_monitor_windows::{subclass_id}")
        if not (0 < cfg.monitoring.alpha <= 1):
            warnings.append(f"invalid_alpha::{subclass_id}")
    return warnings
