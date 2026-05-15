from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from src.llm.predictor import LLMPredictor


NSPF_TOKENS = ("胜", "平", "负")


def extract_nspf_tokens(text: str) -> List[str]:
    raw = str(text or "")
    found: List[Tuple[int, str]] = []
    for token in NSPF_TOKENS:
        pos = raw.find(token)
        if pos >= 0:
            found.append((pos, token))
    found.sort(key=lambda item: item[0])
    return [token for _, token in found]


def cover_from_tokens(tokens: List[str]) -> str:
    seen = []
    for token in tokens or []:
        if token in NSPF_TOKENS and token not in seen:
            seen.append(token)
    return "".join(seen)


def clamp_cover(text: str, *, max_tokens: int = 2) -> str:
    cover = cover_from_tokens(extract_nspf_tokens(text))
    tokens = extract_nspf_tokens(cover)
    if max_tokens and len(tokens) > max_tokens:
        return ""
    return cover


def primary_token_from_display(text: str) -> str:
    tokens = extract_nspf_tokens(text)
    return tokens[0] if tokens else ""


def clean_prediction_result_text(predicted_result: str) -> str:
    value = str(predicted_result or "").strip()
    if not value:
        return ""
    value = value.replace("\\n", "\n").replace("\\r", "\r")
    value = re.split(r"[\n\r]", value, maxsplit=1)[0].strip()
    value = re.split(r"(?:竞彩让球推荐|让球推荐|竞彩置信度|比分参考|进球数参考)", value, maxsplit=1)[0].strip()
    value = value.replace("竞彩推荐（不让球）", "").replace("竞彩推荐", "").replace("不让球推荐", "")
    value = re.sub(r"^[：:\-\s]+", "", value).strip()
    return value


def extract_report_nspf_cover(prediction_text: str, predicted_result: str = "") -> str:
    cleaned_predicted = clean_prediction_result_text(predicted_result or "")
    cover = clamp_cover(cleaned_predicted, max_tokens=2)
    if cover:
        return cover

    details = LLMPredictor.parse_prediction_details(prediction_text or "")
    raw = str(details.get("recommendation_nspf") or "").strip()
    if raw and raw != "暂无":
        first_part = re.split(r"\s*\|\s*", raw, maxsplit=1)[0]
        cover = clamp_cover(first_part, max_tokens=2)
        if cover:
            return cover
    return ""


def _normalize_scores(scores: Dict[str, Any] | None) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for token in NSPF_TOKENS:
        value = 0.0
        if isinstance(scores, dict):
            try:
                value = float(scores.get(token, 0.0) or 0.0)
            except Exception:
                value = 0.0
        out[token] = max(0.0, value)
    return out


def _fallback_distribution(tokens: List[str], primary_token: str) -> List[Tuple[str, float]]:
    if not tokens:
        return []
    if len(tokens) == 1:
        return [(tokens[0], 1.0)]
    if primary_token in tokens:
        remain = max(0.0, 1.0 - 0.6)
        others = [token for token in tokens if token != primary_token]
        share = remain / len(others) if others else 0.0
        ordered = [(primary_token, 0.6)]
        ordered.extend((token, share) for token in others)
        return ordered
    even = 1.0 / len(tokens)
    return [(token, even) for token in tokens]


def _ordered_distribution(
    tokens: List[str],
    scores: Dict[str, Any] | None,
    primary_token: str,
) -> List[Tuple[str, float]]:
    if not tokens:
        return []
    normalized_scores = _normalize_scores(scores)
    total = sum(normalized_scores.get(token, 0.0) for token in tokens)
    if total > 0:
        ordered = [(token, normalized_scores.get(token, 0.0) / total) for token in tokens]
        ordered.sort(key=lambda item: item[1], reverse=True)
        if primary_token:
            ordered.sort(key=lambda item: (item[0] != primary_token, -item[1]))
        return ordered
    return _fallback_distribution(tokens, primary_token)


def _to_percent_list(items: List[Tuple[str, float]]) -> List[Tuple[str, int]]:
    if not items:
        return []
    if len(items) == 1:
        return [(items[0][0], 100)]
    raw = [max(0.0, prob) * 100 for _, prob in items]
    rounded = [int(round(x)) for x in raw]
    delta = 100 - sum(rounded)
    if delta != 0:
        rounded[0] += delta
    return [(items[idx][0], rounded[idx]) for idx in range(len(items))]


def build_pick_summary(
    *,
    cover_text: str,
    scores: Dict[str, Any] | None = None,
    primary_token: str = "",
) -> Dict[str, Any]:
    cover = cover_from_tokens(extract_nspf_tokens(cover_text))
    tokens = extract_nspf_tokens(cover)
    if not tokens:
        return {
            "cover": "",
            "primary": "",
            "pick_type": "none",
            "display": "",
            "distribution": {},
        }

    if len(tokens) == 1:
        token = tokens[0]
        return {
            "cover": cover,
            "primary": token,
            "pick_type": "single",
            "display": token,
            "distribution": {token: 100},
        }

    ordered = _ordered_distribution(tokens, scores, primary_token)
    percentages = _to_percent_list(ordered)
    distribution = {token: pct for token, pct in percentages}
    display = " / ".join(f"{token} {pct}%" for token, pct in percentages)
    return {
        "cover": cover,
        "primary": percentages[0][0] if percentages else "",
        "pick_type": "dual",
        "display": display,
        "distribution": distribution,
    }
