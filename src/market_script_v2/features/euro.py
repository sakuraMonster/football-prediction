from __future__ import annotations

from dataclasses import dataclass

from src.market_script_v2.features.math_utils import iqr, median_or_none, safe_float


@dataclass(frozen=True)
class EuroBookSnapshot:
    book_id: str
    p_home: float | None
    p_draw: float | None
    p_away: float | None


@dataclass(frozen=True)
class EuroConsensus:
    p_home: float | None
    p_draw: float | None
    p_away: float | None
    dispersion: float

    def favored_side(self) -> str:
        if self.p_home is None or self.p_away is None:
            return "none"
        if abs(self.p_home - self.p_away) < 0.03:
            return "none"
        return "home" if self.p_home > self.p_away else "away"


def dominant_shift(open_cons: EuroConsensus, close_cons: EuroConsensus):
    if open_cons.p_home is None or open_cons.p_draw is None or open_cons.p_away is None:
        return None
    if close_cons.p_home is None or close_cons.p_draw is None or close_cons.p_away is None:
        return None
    deltas = {
        "home": close_cons.p_home - open_cons.p_home,
        "draw": close_cons.p_draw - open_cons.p_draw,
        "away": close_cons.p_away - open_cons.p_away,
    }
    side = max(deltas.keys(), key=lambda k: abs(deltas[k]))
    return side, deltas[side], deltas


def implied_probs(odds_h, odds_d, odds_a):
    h = safe_float(odds_h)
    d = safe_float(odds_d)
    a = safe_float(odds_a)
    if h is None or d is None or a is None or h <= 1.0001 or d <= 1.0001 or a <= 1.0001:
        return None
    inv_h = 1.0 / h
    inv_d = 1.0 / d
    inv_a = 1.0 / a
    s = inv_h + inv_d + inv_a
    if s <= 0:
        return None
    return (inv_h / s, inv_d / s, inv_a / s)


def build_euro_book_snapshot(row: dict) -> EuroBookSnapshot | None:
    probs = implied_probs(row.get("odds_h"), row.get("odds_d"), row.get("odds_a"))
    if probs is None:
        return None
    p_home, p_draw, p_away = probs
    return EuroBookSnapshot(
        book_id=str(row.get("book_id") or "unknown"),
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
    )


def consensus_from_books(books: list[EuroBookSnapshot]) -> EuroConsensus:
    p_home = median_or_none([b.p_home for b in books])
    p_draw = median_or_none([b.p_draw for b in books])
    p_away = median_or_none([b.p_away for b in books])
    disp = iqr([b.p_home for b in books]) + iqr([b.p_away for b in books])
    return EuroConsensus(p_home=p_home, p_draw=p_draw, p_away=p_away, dispersion=disp)
