from __future__ import annotations

from dataclasses import dataclass

from src.market_script_v2.features.math_utils import median_or_none, safe_float


HANDICAP_MAP = {
    "平手": 0.0,
    "平手/半球": 0.25,
    "半球": 0.5,
    "半球/一球": 0.75,
    "一球": 1.0,
    "一球/球半": 1.25,
    "球半": 1.5,
    "球半/两球": 1.75,
    "两球": 2.0,
    "两球/两球半": 2.25,
    "两球半": 2.5,
    "受平手/半球": -0.25,
    "受半球": -0.5,
    "受半球/一球": -0.75,
    "受一球": -1.0,
    "受一球/球半": -1.25,
    "受球半": -1.5,
    "受球半/两球": -1.75,
    "受两球": -2.0,
    "受两球/两球半": -2.25,
    "受两球半": -2.5,
}


@dataclass(frozen=True)
class AsianBookSnapshot:
    book_id: str
    hv: float | None
    giving_w: float | None
    receiving_w: float | None


@dataclass(frozen=True)
class AsianConsensus:
    hv: float | None
    giving_w: float | None
    receiving_w: float | None


def _handicap_value(text: str) -> float | None:
    key = str(text or "").replace(" ", "")
    return HANDICAP_MAP.get(key)


def _normalize_price(text: str):
    value = safe_float(text)
    return value


def build_asian_book_snapshot(row: dict) -> AsianBookSnapshot | None:
    hv = _handicap_value(row.get("ah_line") or "")
    if hv is None:
        return None
    w1 = _normalize_price(row.get("price_home"))
    w2 = _normalize_price(row.get("price_away"))
    if w1 is None or w2 is None:
        return None
    giving_w = w1 if hv >= 0 else w2
    receiving_w = w2 if hv >= 0 else w1
    return AsianBookSnapshot(
        book_id=str(row.get("book_id") or "unknown"),
        hv=hv,
        giving_w=giving_w,
        receiving_w=receiving_w,
    )


def consensus_from_books(books: list[AsianBookSnapshot]) -> AsianConsensus:
    hv = median_or_none([b.hv for b in books])
    giving_w = median_or_none([b.giving_w for b in books])
    receiving_w = median_or_none([b.receiving_w for b in books])
    return AsianConsensus(hv=hv, giving_w=giving_w, receiving_w=receiving_w)


def ah_supports_favored(favored_side: str, hv_open: float | None, hv_close: float | None) -> bool | None:
    if hv_open is None or hv_close is None:
        return None
    if favored_side == "home":
        return hv_close > hv_open + 1e-9
    if favored_side == "away":
        return hv_close < hv_open - 1e-9
    return None


def is_cross_key_number(hv_open: float | None, hv_close: float | None) -> bool:
    if hv_open is None or hv_close is None:
        return False
    return abs(hv_close - hv_open) >= 0.24


def key_number_hold_with_price_swings(series: list[AsianConsensus]) -> bool:
    if len(series) < 3:
        return False
    hv_values = [s.hv for s in series if s.hv is not None]
    if len(hv_values) < 3:
        return False
    if max(hv_values) - min(hv_values) > 1e-9:
        return False
    prices = [s.giving_w for s in series if s.giving_w is not None]
    if len(prices) < 3:
        return False
    return (max(prices) - min(prices)) >= 0.08
