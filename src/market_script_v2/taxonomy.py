from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class V2Prototype:
    prototype_id: str
    name: str
    default_action: str
    required_features: list[str]
    notes: list[str]


def _default_taxonomy_path() -> Path:
    return Path("data") / "rules" / "market_script_v2_taxonomy.json"


def load_v2_taxonomy(path: str | None = None) -> dict[str, V2Prototype]:
    p = Path(path) if path else _default_taxonomy_path()
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    items = raw.get("prototypes") or []
    out: dict[str, V2Prototype] = {}
    for item in items:
        pid = str(item.get("prototype_id") or "").strip()
        if not pid:
            continue
        out[pid] = V2Prototype(
            prototype_id=pid,
            name=str(item.get("name") or ""),
            default_action=str(item.get("default_action") or ""),
            required_features=[str(x) for x in (item.get("required_features") or []) if str(x)],
            notes=[str(x) for x in (item.get("notes") or []) if str(x)],
        )
    return out

