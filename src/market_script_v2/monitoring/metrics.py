from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowMetrics:
    n: int
    clv_rate: float | None
    clv_magnitude: float | None
    dispersion: float | None


def ewma(prev: float | None, current: float | None, alpha: float) -> float | None:
    if current is None:
        return prev
    if prev is None:
        return float(current)
    return float(alpha * current + (1 - alpha) * prev)


def compute_window_metrics(rows: list[dict]) -> WindowMetrics:
    clv = [r.get("clv_prob") for r in rows if r.get("clv_prob") is not None]
    n = len(clv)
    if n == 0:
        return WindowMetrics(n=0, clv_rate=None, clv_magnitude=None, dispersion=None)
    positive = sum(1 for v in clv if v > 0)
    clv_rate = positive / n
    clv_magnitude = sum(clv) / n
    disp = [r.get("dispersion") for r in rows if r.get("dispersion") is not None]
    dispersion = (sum(disp) / len(disp)) if disp else None
    return WindowMetrics(n=n, clv_rate=clv_rate, clv_magnitude=clv_magnitude, dispersion=dispersion)

