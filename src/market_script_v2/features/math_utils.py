from __future__ import annotations

from statistics import median


def safe_float(value):
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"0", "0.0"}:
            return None
        return float(text)
    except Exception:
        return None


def median_or_none(values):
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return float(median(cleaned))


def iqr(values):
    cleaned = sorted([v for v in values if v is not None])
    if len(cleaned) < 4:
        return 0.0
    q1_idx = int((len(cleaned) - 1) * 0.25)
    q3_idx = int((len(cleaned) - 1) * 0.75)
    return float(cleaned[q3_idx] - cleaned[q1_idx])

