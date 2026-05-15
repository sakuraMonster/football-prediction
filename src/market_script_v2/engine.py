from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from src.db.database import Database
from src.market_script_v2.models import MarketScriptV2Output
from src.market_script_v2.config import load_v2_subclass_configs
from src.market_script_v2.config import validate_v2_configs
from src.market_script_v2.classifier import MatchFeatures, select_best_subclass
from src.market_script_v2.bias_config import load_v2_prediction_bias_params
from src.market_script_v2.decision_weights import load_v2_decision_weights
from src.market_script_v2.features.time_buckets import bucket_by_kickoff, parse_datetime_maybe
from src.market_script_v2.features.euro import (
    build_euro_book_snapshot,
    consensus_from_books as euro_consensus_from_books,
    dominant_shift,
)
from src.market_script_v2.features.asian import (
    build_asian_book_snapshot,
    consensus_from_books as ah_consensus_from_books,
    ah_supports_favored,
    is_cross_key_number,
    key_number_hold_with_price_swings,
)


class MarketScriptV2Engine:
    ENGINE_VERSION = "0.1.0"

    def __init__(self, db: Optional[Database] = None):
        self._db = db
        self._subclass_cfg = load_v2_subclass_configs()
        self._config_warnings = validate_v2_configs(self._subclass_cfg)

    def analyze(
        self,
        *,
        fixture_id: str,
        prediction_period: str,
        match_data: dict[str, Any],
        mode: str,
    ) -> MarketScriptV2Output:
        fixture_id = str(fixture_id or "").strip()
        prediction_period = str(prediction_period or "").strip() or "final"
        mode = str(mode or "shadow").strip()

        output = self._analyze_core(
            fixture_id=fixture_id,
            prediction_period=prediction_period,
            match_data=match_data,
            mode=mode,
        )

        try:
            db = self._db or Database()
            db.save_v2_script_output(output)
            if self._db is None:
                db.close()
        except Exception as e:
            logger.warning(f"v2 输出落库失败 fixture_id={fixture_id}: {e}")

        return output

    @staticmethod
    def _bias_to_tokens(bias: str) -> list[str]:
        mapping = {
            "胜": ["胜"],
            "平": ["平"],
            "负": ["负"],
            "胜平": ["胜", "平"],
            "平负": ["平", "负"],
            "胜负": ["胜", "负"],
        }
        return mapping.get(str(bias or "").strip(), [])

    @staticmethod
    def _tokens_to_bias(tokens: list[str]) -> str:
        canonical = [token for token in ["胜", "平", "负"] if token in set(tokens or [])]
        mapping = {
            ("胜",): "胜",
            ("平",): "平",
            ("负",): "负",
            ("胜", "平"): "胜平",
            ("平", "负"): "平负",
            ("胜", "负"): "胜负",
        }
        return mapping.get(tuple(canonical), "")

    @staticmethod
    def _token_for_favored(favored: str) -> str:
        if favored == "home":
            return "胜"
        if favored == "away":
            return "负"
        return "平"

    @staticmethod
    def _token_for_underdog(favored: str) -> str:
        if favored == "home":
            return "负"
        if favored == "away":
            return "胜"
        return "平"

    @staticmethod
    def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
        bounded = {k: max(0.0001, float(v or 0.0)) for k, v in (scores or {}).items()}
        total = sum(bounded.values())
        if total <= 0:
            return {"胜": 0.3333, "平": 0.3333, "负": 0.3334}
        return {k: round(v / total, 4) for k, v in bounded.items()}

    @classmethod
    def _build_upset_alert(
        cls,
        *,
        favored: str,
        subclass: str,
        action_type: str,
        direction_hint: str,
        dispersion: Optional[float],
        status: Optional[str],
        euro_favored_prob_delta: Optional[float],
        draw_prob_delta: Optional[float],
        weights: dict[str, Any],
        top1: str,
        top2: str,
    ) -> dict[str, Any]:
        upset_cfg = dict(weights.get("upset_alert") or {})
        score = 0.0
        reasons: list[str] = []
        subclass_l = str(subclass or "").lower()
        hint = str(direction_hint or "")

        def _add(condition: bool, key: str, default: float, reason: str):
            nonlocal score
            if condition:
                score += float(upset_cfg.get(key, default))
                reasons.append(reason)

        _add("popular_tax" in subclass_l, "popular_tax_score", 20, "popular_tax")
        _add("popular_deepening" in subclass_l, "popular_deepening_score", 18, "popular_deepening")
        _add("divergence" in subclass_l, "divergence_score", 20, "divergence")
        _add("draw_shaping" in subclass_l, "draw_shaping_score", 12, "draw_shaping")
        _add("late_correction" in subclass_l, "late_correction_score", 8, "late_correction")

        _add(euro_favored_prob_delta is not None and euro_favored_prob_delta <= -0.02, "fade_favored_score", 18, "fade_favored")
        _add(draw_prob_delta is not None and draw_prob_delta >= 0.015, "draw_up_score", 14, "draw_up")
        _add(dispersion is not None and dispersion >= 0.08, "high_dispersion_score", 10, "high_dispersion")
        _add(str(status or "").lower() == "black", "black_status_score", 12, "black_status")
        _add(str(action_type or "").lower() == "diagnosis", "diagnosis_score", 8, "diagnosis")
        _add("防平" in hint, "guard_draw_score", 8, "guard_draw")
        _add(any(k in hint for k in ["谨慎", "避免单挑", "不单挑"]), "avoid_single_score", 10, "avoid_single")

        medium_threshold = float(upset_cfg.get("medium_threshold", 40))
        high_threshold = float(upset_cfg.get("high_threshold", 60))
        level = "none"
        if score >= high_threshold:
            level = "high"
        elif score >= medium_threshold:
            level = "medium"
        elif score > 0:
            level = "low"

        direction = ""
        guard_pick = ""
        if any(k in reasons for k in ["draw_shaping", "draw_up", "guard_draw"]):
            direction = "平局冷门"
            guard_pick = "平"
        elif any(k in reasons for k in ["popular_deepening", "fade_favored", "divergence"]):
            direction = "弱势方冷门"
            guard_pick = cls._tokens_to_bias([top1, top2]) if top1 and top2 else ""
        elif level in {"medium", "high"}:
            direction = "热门翻车风险"
            guard_pick = cls._tokens_to_bias([top1, top2]) if top1 and top2 else ""

        if not guard_pick and level in {"medium", "high"}:
            guard_pick = cls._tokens_to_bias([top1, top2]) if top1 and top2 else ""

        if favored == "home" and direction == "弱势方冷门" and not guard_pick:
            guard_pick = "平负"
        elif favored == "away" and direction == "弱势方冷门" and not guard_pick:
            guard_pick = "胜平"

        return {
            "level": level,
            "score": int(round(score)),
            "direction": direction,
            "reasons": reasons,
            "guard_pick": guard_pick,
        }

    @classmethod
    def _build_nspf_decision(
        cls,
        *,
        league: str,
        favored: str,
        subclass: str,
        action_type: str,
        strength: str,
        prediction_bias: str,
        direction_hint: str,
        dispersion: Optional[float],
        status: Optional[str],
        euro_close,
        euro_favored_prob_delta: Optional[float],
        draw_prob_delta: Optional[float],
    ) -> dict[str, Any]:
        base_scores = {
            "胜": float(getattr(euro_close, "p_home", None) or 0.3333),
            "平": float(getattr(euro_close, "p_draw", None) or 0.3333),
            "负": float(getattr(euro_close, "p_away", None) or 0.3334),
        }
        scores = dict(base_scores)
        reasons = []
        weights = load_v2_decision_weights(league=league, dispersion=dispersion)
        bias_single_bonus = float(weights.get("bias_single_bonus", 0.12))
        bias_double_bonus = float(weights.get("bias_double_bonus", 0.07))
        single_gap_threshold = float(weights.get("single_gap_threshold", 0.12))
        high_dispersion_penalty_gap = float(weights.get("high_dispersion_penalty_gap", 0.02))
        white_status_gap_bonus = float(weights.get("white_status_gap_bonus", 0.02))
        top1_base_confidence = float(weights.get("top1_base_confidence", 56))
        top1_gap_scale = float(weights.get("top1_gap_scale", 120))

        favored_token = cls._token_for_favored(favored)
        underdog_token = cls._token_for_underdog(favored)
        strength_factor = {"weak": 0.7, "medium": 1.0, "strong": 1.2}.get(strength, 0.85)
        bias_tokens = cls._bias_to_tokens(prediction_bias)
        if bias_tokens:
            bias_bonus = (bias_single_bonus if len(bias_tokens) == 1 else bias_double_bonus) * strength_factor
            for token in bias_tokens:
                scores[token] += bias_bonus
            reasons.append(f"bias={prediction_bias}")

        subclass_l = str(subclass or "").lower()
        subclass_weights = weights.get("subclass", {}).get(subclass_l, {})
        if "draw_shaping" in subclass_l:
            scores["平"] += float(subclass_weights.get("draw_bonus", 0.10))
            reasons.append("draw_shaping")
        if "popular_tax" in subclass_l:
            scores["平"] += float(subclass_weights.get("draw_bonus", 0.08))
            if favored_token:
                scores[favored_token] -= float(subclass_weights.get("favored_penalty", 0.03))
            reasons.append("popular_tax")
        if "popular_deepening" in subclass_l:
            scores["平"] += float(subclass_weights.get("draw_bonus", 0.05))
            if underdog_token:
                scores[underdog_token] += float(subclass_weights.get("underdog_bonus", 0.04))
            reasons.append("popular_deepening")
        if "divergence" in subclass_l:
            scores["平"] += float(subclass_weights.get("draw_bonus", 0.03))
            reasons.append("divergence")
        if "late_correction" in subclass_l:
            scores["平"] += float(subclass_weights.get("draw_bonus", 0.02))
            reasons.append("late_correction")
        if "info_shock" in subclass_l and favored_token:
            scores[favored_token] += float(subclass_weights.get("favored_bonus", 0.08)) * strength_factor
            reasons.append("info_shock")

        if favored_token and euro_favored_prob_delta is not None:
            if euro_favored_prob_delta >= 0.02:
                scores[favored_token] += min(0.08, euro_favored_prob_delta * 2.0)
                reasons.append("support_favored")
            elif euro_favored_prob_delta <= -0.02:
                scores[favored_token] -= min(0.06, abs(euro_favored_prob_delta) * 1.5)
                scores["平"] += min(0.05, abs(euro_favored_prob_delta))
                if underdog_token:
                    scores[underdog_token] += min(0.04, abs(euro_favored_prob_delta))
                reasons.append("fade_favored")

        if draw_prob_delta is not None:
            if draw_prob_delta >= 0.015:
                scores["平"] += min(0.10, draw_prob_delta * 3.0)
                reasons.append("draw_up")
            elif draw_prob_delta <= -0.015:
                scores["平"] -= min(0.06, abs(draw_prob_delta) * 2.5)
                reasons.append("draw_down")

        if "防平" in str(direction_hint or ""):
            scores["平"] += 0.05
            reasons.append("hint_guard_draw")
        if any(k in str(direction_hint or "") for k in ["谨慎", "避免单挑", "不单挑"]):
            reasons.append("hint_avoid_single")

        scores = cls._normalize_scores(scores)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top1, top1_score = ordered[0]
        top2, top2_score = ordered[1]
        gap = top1_score - top2_score
        upset_alert = cls._build_upset_alert(
            favored=favored,
            subclass=subclass,
            action_type=action_type,
            direction_hint=direction_hint,
            dispersion=dispersion,
            status=status,
            euro_favored_prob_delta=euro_favored_prob_delta,
            draw_prob_delta=draw_prob_delta,
            weights=weights,
            top1=top1,
            top2=top2,
        )

        force_dual = False
        if str(action_type or "").lower() == "diagnosis":
            force_dual = True
        if str(status or "").lower() == "black":
            force_dual = True
        if "divergence" in subclass_l or "popular_" in subclass_l:
            force_dual = True
        if dispersion is not None and dispersion >= 0.09:
            force_dual = True
        if any(k in str(direction_hint or "") for k in ["谨慎", "避免单挑", "不单挑"]):
            force_dual = True

        threshold = single_gap_threshold
        if strength == "strong":
            threshold = 0.10
        elif strength == "weak":
            threshold = 0.14
        if dispersion is not None and dispersion >= 0.08:
            threshold += high_dispersion_penalty_gap
        if str(status or "").lower() == "white":
            threshold -= white_status_gap_bonus

        if not force_dual and gap >= threshold:
            cover = top1
            feedback_tag = "single_strong"
        else:
            cover = cls._tokens_to_bias([top1, top2])
            feedback_tag = "double_guarded"

        confidence = int(round(top1_base_confidence + gap * top1_gap_scale))
        confidence += {"weak": -2, "medium": 2, "strong": 5}.get(strength, 0)
        if cover != top1:
            confidence = min(confidence, 64)
        if str(action_type or "").lower() == "diagnosis":
            confidence = min(confidence, 58)
        if str(status or "").lower() == "black":
            confidence = min(confidence, 56)
        if dispersion is not None and dispersion >= 0.10:
            confidence -= 4
        confidence = max(50, min(75, confidence))

        if cover == "平":
            feedback_tag = "draw_lean"

        reason = (
            f"base={base_scores['胜']:.3f}/{base_scores['平']:.3f}/{base_scores['负']:.3f}; "
            f"decision={top1}->{cover}; gap={gap:.3f}; "
            f"signals={','.join(reasons[:5]) if reasons else 'base_only'}"
        )
        return {
            "top1": top1,
            "cover": cover,
            "confidence": confidence,
            "scores": scores,
            "reason": reason,
            "feedback_tag": feedback_tag,
            "upset_alert": upset_alert,
        }

    def _analyze_core(
        self,
        *,
        fixture_id: str,
        prediction_period: str,
        match_data: dict[str, Any],
        mode: str,
    ) -> MarketScriptV2Output:
        now = datetime.now()

        kickoff_time = parse_datetime_maybe(match_data.get("match_time") or match_data.get("kickoff_time"))
        league_name = str(match_data.get("league") or "")
        try:
            db = self._db or Database()
            euro_rows = db.fetch_v2_odds_snapshots(fixture_id)
            ah_rows = db.fetch_v2_ah_snapshots(fixture_id)
            if self._db is None:
                db.close()
        except Exception:
            euro_rows = []
            ah_rows = []

        euro_rows = [r for r in euro_rows if (r.get("quality_flag") or 0) == 0]
        ah_rows = [r for r in ah_rows if (r.get("quality_flag") or 0) == 0]

        euro_bucketed = bucket_by_kickoff(euro_rows, kickoff_time)
        ah_bucketed = bucket_by_kickoff(ah_rows, kickoff_time)

        bucket_count = sum(1 for count in euro_bucketed.bucket_counts().values() if count > 0)
        if bucket_count < 3:
            return MarketScriptV2Output(
                fixture_id=fixture_id,
                prediction_period=prediction_period,
                league=league_name,
                mode=mode,
                engine_version=self.ENGINE_VERSION,
                prototype="insufficient_data",
                subclass="insufficient_data",
                action_type="Diagnosis",
                strength="weak",
                prediction_bias="",
                direction_hint="",
                why="v2 缺少足够欧赔时间序列（至少 3 个时间桶）",
                veto_tags=[],
                signal_bucket="",
                clv_prob=None,
                clv_logit=None,
                dispersion=None,
                created_at=now,
            )

        euro_open_books = [build_euro_book_snapshot(r) for r in euro_bucketed.open]
        euro_open_books = [b for b in euro_open_books if b is not None]
        euro_close_books = [build_euro_book_snapshot(r) for r in euro_bucketed.close]
        euro_close_books = [b for b in euro_close_books if b is not None]
        euro_mid_books = [build_euro_book_snapshot(r) for r in euro_bucketed.t_6]
        euro_mid_books = [b for b in euro_mid_books if b is not None]

        euro_open = euro_consensus_from_books(euro_open_books)
        euro_close = euro_consensus_from_books(euro_close_books)
        euro_mid = euro_consensus_from_books(euro_mid_books) if euro_mid_books else None

        euro_t24_books = [build_euro_book_snapshot(r) for r in euro_bucketed.t_24]
        euro_t24_books = [b for b in euro_t24_books if b is not None]
        euro_t24 = euro_consensus_from_books(euro_t24_books) if euro_t24_books else None

        euro_t12_books = [build_euro_book_snapshot(r) for r in euro_bucketed.t_12]
        euro_t12_books = [b for b in euro_t12_books if b is not None]
        euro_t12 = euro_consensus_from_books(euro_t12_books) if euro_t12_books else None

        euro_t1_books = [build_euro_book_snapshot(r) for r in euro_bucketed.t_1]
        euro_t1_books = [b for b in euro_t1_books if b is not None]
        euro_t1 = euro_consensus_from_books(euro_t1_books) if euro_t1_books else None

        favored = euro_open.favored_side()

        ah_open_books = [build_asian_book_snapshot(r) for r in ah_bucketed.open]
        ah_open_books = [b for b in ah_open_books if b is not None]
        ah_close_books = [build_asian_book_snapshot(r) for r in ah_bucketed.close]
        ah_close_books = [b for b in ah_close_books if b is not None]
        ah_mid_books = [build_asian_book_snapshot(r) for r in ah_bucketed.t_6]
        ah_mid_books = [b for b in ah_mid_books if b is not None]

        ah_open = ah_consensus_from_books(ah_open_books) if ah_open_books else None
        ah_close = ah_consensus_from_books(ah_close_books) if ah_close_books else None
        ah_mid = ah_consensus_from_books(ah_mid_books) if ah_mid_books else None

        ah_series = [x for x in [ah_open, ah_mid, ah_close] if x is not None]

        ah_t24_books = [build_asian_book_snapshot(r) for r in ah_bucketed.t_24]
        ah_t24_books = [b for b in ah_t24_books if b is not None]
        ah_t24 = ah_consensus_from_books(ah_t24_books) if ah_t24_books else None

        ah_t12_books = [build_asian_book_snapshot(r) for r in ah_bucketed.t_12]
        ah_t12_books = [b for b in ah_t12_books if b is not None]
        ah_t12 = ah_consensus_from_books(ah_t12_books) if ah_t12_books else None

        ah_t1_books = [build_asian_book_snapshot(r) for r in ah_bucketed.t_1]
        ah_t1_books = [b for b in ah_t1_books if b is not None]
        ah_t1 = ah_consensus_from_books(ah_t1_books) if ah_t1_books else None

        def favored_p(cons):
            if cons is None:
                return None
            if favored == "home":
                return cons.p_home
            if favored == "away":
                return cons.p_away
            return None

        p_open = favored_p(euro_open)
        p_t24 = favored_p(euro_t24) if euro_t24 else None
        p_t12 = favored_p(euro_t12) if euro_t12 else None
        p_close = favored_p(euro_close)
        p_mid = favored_p(euro_mid) if euro_mid else None
        p_t1 = favored_p(euro_t1) if euro_t1 else None

        euro_favored_prob_delta = None
        if p_open is not None and p_close is not None:
            euro_favored_prob_delta = p_close - p_open

        draw_prob_delta = None
        try:
            if euro_open.p_draw is not None and euro_close.p_draw is not None:
                draw_prob_delta = euro_close.p_draw - euro_open.p_draw
        except Exception:
            draw_prob_delta = None

        def _fmt_prob(x: Optional[float]) -> str:
            if x is None:
                return "-"
            return f"{x:.3f}"

        def _fmt_delta(x: Optional[float]) -> str:
            if x is None:
                return "-"
            return f"{x:+.3f}"

        ah_line_cross = False
        if ah_open and ah_close and ah_open.hv is not None and ah_close.hv is not None:
            ah_line_cross = is_cross_key_number(ah_open.hv, ah_close.hv)

        ah_price_swing = None
        if ah_open and ah_close and ah_open.giving_w is not None and ah_close.giving_w is not None:
            ah_price_swing = abs(ah_close.giving_w - ah_open.giving_w)

        def _first_euro_move_bucket(threshold=0.015):
            if p_open is None:
                return None
            for bucket, p in [("T-24", p_t24), ("T-12", p_t12), ("T-6", p_mid), ("T-1", p_t1), ("close", p_close)]:
                if p is None:
                    continue
                if abs(p - p_open) >= threshold:
                    return bucket
            return None

        def _first_ah_move_bucket(line_threshold=0.24, price_threshold=0.08):
            if ah_open is None:
                return None
            hv0 = ah_open.hv
            w0 = ah_open.giving_w
            for bucket, cons in [("T-24", ah_t24), ("T-12", ah_t12), ("T-6", ah_mid), ("T-1", ah_t1), ("close", ah_close)]:
                if cons is None:
                    continue
                hv = cons.hv
                w = cons.giving_w
                if hv0 is not None and hv is not None and abs(hv - hv0) >= line_threshold:
                    return bucket
                if w0 is not None and w is not None and abs(w - w0) >= price_threshold:
                    return bucket
            return None

        euro_first_bucket = _first_euro_move_bucket()
        ah_first_bucket = _first_ah_move_bucket()

        who_moves_first = "unknown"
        order = {"T-24": 1, "T-12": 2, "T-6": 3, "T-1": 4, "close": 5}
        if euro_first_bucket and ah_first_bucket:
            who_moves_first = "euro_first" if order[euro_first_bucket] < order[ah_first_bucket] else "asian_first" if order[ah_first_bucket] < order[euro_first_bucket] else "sync"
        elif euro_first_bucket and not ah_first_bucket:
            who_moves_first = "euro_first"
        elif ah_first_bucket and not euro_first_bucket:
            who_moves_first = "asian_first"

        velocity_bucket = "unknown"
        try:
            if p_open is not None and p_close is not None and euro_bucketed.open and euro_bucketed.close:
                t0 = euro_bucketed.open[0]["snapshot_time"]
                t1 = euro_bucketed.close[-1]["snapshot_time"]
                hours = max(0.5, (t1 - t0).total_seconds() / 3600.0)
                vel = abs(p_close - p_open) / hours
                velocity_bucket = "fast" if vel >= 0.006 else "slow"
        except Exception:
            velocity_bucket = "unknown"

        convergence_flag = False
        try:
            if euro_open.dispersion is not None and euro_close.dispersion is not None:
                convergence_flag = (euro_open.dispersion - euro_close.dispersion) >= 0.05 and euro_close.dispersion <= 0.06
        except Exception:
            convergence_flag = False

        euro_dir = None
        if p_open is not None and p_close is not None:
            euro_dir = "support_favored" if (p_close - p_open) > 0.01 else "fade_favored" if (p_close - p_open) < -0.01 else "flat"

        head_fake = False
        head_fake_d1 = None
        head_fake_d2 = None
        if p_open is not None and p_mid is not None and p_close is not None:
            d1 = p_mid - p_open
            d2 = p_close - p_mid
            if abs(d1) >= 0.015 and abs(d2) >= 0.015 and (d1 * d2) < 0:
                head_fake = True
                head_fake_d1 = d1
                head_fake_d2 = d2

        ah_support = None
        if ah_open and ah_close:
            ah_support = ah_supports_favored(favored, ah_open.hv, ah_close.hv)

        divergence = False
        if euro_dir in {"support_favored", "fade_favored"} and ah_support is not None:
            if euro_dir == "support_favored" and ah_support is False:
                divergence = True
            if euro_dir == "fade_favored" and ah_support is True:
                divergence = True

        draw_dom_delta = None

        prototype = "risk_balancing"
        subclass = "risk_balancing"
        action_type = "Risk"
        strength = "weak"
        prediction_bias = ""
        direction_hint = ""
        signal_bucket = ""
        why_parts = []

        try:
            conv_text = "是" if convergence_flag else "否"
            why_parts.append(
                "欧赔变化："
                f"favored={favored}；"
                f"H/D/A { _fmt_prob(euro_open.p_home) }/{ _fmt_prob(euro_open.p_draw) }/{ _fmt_prob(euro_open.p_away) }"
                f"→{ _fmt_prob(euro_close.p_home) }/{ _fmt_prob(euro_close.p_draw) }/{ _fmt_prob(euro_close.p_away) }；"
                f"强势方Δp={ _fmt_delta(euro_favored_prob_delta) } 平局Δp={ _fmt_delta(draw_prob_delta) }；"
                f"分歧 { _fmt_prob(euro_open.dispersion) }→{ _fmt_prob(euro_close.dispersion) }；"
                f"先动={who_moves_first} 速度={velocity_bucket} 收敛={conv_text}"
            )
        except Exception:
            pass

        try:
            if ah_open and ah_close:
                hv0 = ah_open.hv
                hv1 = ah_close.hv
                w0 = ah_open.giving_w
                w1 = ah_close.giving_w
                why_parts.append(
                    "亚盘变化："
                    f"让步 {hv0 if hv0 is not None else '-'}→{hv1 if hv1 is not None else '-'}；"
                    f"让球方水位 { _fmt_prob(w0) }→{ _fmt_prob(w1) }"
                )
        except Exception:
            pass

        if head_fake:
            prototype = "head_fake"
            subclass = "head_fake_v_reversal"
            action_type = "Diagnosis"
            strength = "weak"
            prediction_bias = ""
            signal_bucket = "T-6"
            why_parts.append(
                f"试盘回撤：d1={_fmt_delta(head_fake_d1)} d2={_fmt_delta(head_fake_d2)}（先上修后回撤/或相反）"
            )
        elif divergence:
            prototype = "cross_market_divergence"
            subclass = "divergence_euro_vs_ah"
            action_type = "Risk"
            strength = "medium" if euro_open.dispersion <= 0.06 else "weak"
            if favored == "home":
                prediction_bias = "平负"
            elif favored == "away":
                prediction_bias = "胜平"
            else:
                prediction_bias = ""
            signal_bucket = "close"
            why_parts.append(
                f"欧亚背离：euro_dir={euro_dir} ah_supports_favored={ah_support}（欧赔与亚盘给出相反信号）"
            )
        else:
            classified = False
            shift = dominant_shift(euro_open, euro_close)
            if shift is not None:
                dom_side, dom_delta, deltas = shift
                if dom_side == "draw":
                    draw_dom_delta = dom_delta
                if dom_side == "draw" and abs(dom_delta) >= 0.02:
                    prototype = "draw_shaping"
                    subclass = "draw_shaping_draw_driven"
                    action_type = "Risk"
                    strength = "medium" if euro_open.dispersion <= 0.06 else "weak"
                    direction_hint = "优先防平" if strength != "weak" else ""
                    prediction_bias = "平"
                    why_parts.append(f"平驱动：dominant_shift=draw Δ={_fmt_delta(dom_delta)}")
                    signal_bucket = "close"
                    classified = True
                elif ah_open and ah_close and is_cross_key_number(ah_open.hv, ah_close.hv):
                    prototype = "late_correction"
                    subclass = "late_correction_key_cross"
                    action_type = "Risk"
                    strength = "medium" if euro_open.dispersion <= 0.06 else "weak"
                    if favored == "home":
                        prediction_bias = "平负"
                    elif favored == "away":
                        prediction_bias = "胜平"
                    else:
                        prediction_bias = ""
                    why_parts.append(
                        f"临场跨档：让步 {ah_open.hv if ah_open.hv is not None else '-'}→{ah_close.hv if ah_close.hv is not None else '-'}"
                    )
                    signal_bucket = "close"
                    classified = True
                elif convergence_flag and abs((p_close or 0) - (p_open or 0)) >= 0.02:
                    prototype = "late_correction"
                    subclass = "late_correction_convergence"
                    action_type = "Risk"
                    strength = "medium"
                    if favored == "home":
                        prediction_bias = "平负"
                    elif favored == "away":
                        prediction_bias = "胜平"
                    else:
                        prediction_bias = ""
                    why_parts.append(
                        f"收敛纠偏：disp { _fmt_prob(euro_open.dispersion) }→{ _fmt_prob(euro_close.dispersion) }"
                    )
                    signal_bucket = "close"
                    classified = True
                elif key_number_hold_with_price_swings(ah_series):
                    prototype = "key_number_mgmt"
                    subclass = "key_number_hold"
                    action_type = "Diagnosis"
                    strength = "weak"
                    prediction_bias = ""
                    why_parts.append(
                        f"顶住不跨：ah_line_cross={ah_line_cross} 让球方水位波动≈{_fmt_prob(ah_price_swing)}"
                    )
                    signal_bucket = "T-6"
                    classified = True

            if not classified and favored in {"home", "away"} and (euro_favored_prob_delta is not None):
                draw_delta = None
                try:
                    draw_delta = deltas.get("draw") if shift is not None else (euro_close.p_draw - euro_open.p_draw)
                except Exception:
                    draw_delta = None
                if euro_favored_prob_delta <= -0.02 and (draw_delta is not None) and draw_delta >= 0.015:
                    prototype = "public_pressure"
                    subclass = "public_pressure_popular_tax"
                    action_type = "Risk"
                    strength = "medium" if euro_open.dispersion <= 0.06 else "weak"
                    direction_hint = "避免单挑热门，优先防平" if strength != "weak" else ""
                    prediction_bias = "平"
                    why_parts.append(
                        f"热门加税：强势方Δp={_fmt_delta(euro_favored_prob_delta)} 平局Δp={_fmt_delta(draw_delta)}"
                    )
                    signal_bucket = "close"
                    classified = True

            if not classified and favored in {"home", "away"} and ah_line_cross and (euro_favored_prob_delta is not None) and abs(euro_favored_prob_delta) <= 0.01:
                prototype = "public_pressure"
                subclass = "public_pressure_popular_deepening"
                action_type = "Risk"
                strength = "medium" if euro_open.dispersion <= 0.06 else "weak"
                direction_hint = "深盘但欧赔不支持，谨慎追热门" if strength != "weak" else ""
                prediction_bias = "平负" if favored == "home" else "胜平"
                why_parts.append(
                    f"深盘引导：让步跨档且强势方Δp={_fmt_delta(euro_favored_prob_delta)}（欧赔不跟随）"
                )
                signal_bucket = "close"
                classified = True

            if not classified and euro_open.dispersion >= 0.10:
                prototype = "risk_balancing"
                subclass = "high_dispersion"
                action_type = "Diagnosis"
                strength = "weak"
                prediction_bias = ""
                why_parts.append(f"高分歧：open_disp={_fmt_prob(euro_open.dispersion)}")
                signal_bucket = "close"
                classified = True

            if not classified and (not ah_line_cross) and (ah_price_swing is not None) and ah_price_swing >= 0.08 and (euro_favored_prob_delta is not None) and abs(euro_favored_prob_delta) <= 0.01:
                prototype = "risk_balancing"
                subclass = "risk_balancing_price_only"
                action_type = "Diagnosis"
                strength = "weak"
                prediction_bias = ""
                why_parts.append(
                    f"只动水：ah_line_cross={ah_line_cross} 水位波动≈{_fmt_prob(ah_price_swing)} 强势方Δp={_fmt_delta(euro_favored_prob_delta)}"
                )
                signal_bucket = "T-6"
                classified = True

            if not classified and (euro_favored_prob_delta is not None) and abs(euro_favored_prob_delta) <= 0.01 and euro_open.dispersion <= 0.08:
                prototype = "risk_balancing"
                subclass = "risk_balancing_flat_drift"
                action_type = "Risk"
                strength = "weak"
                prediction_bias = ""
                why_parts.append(
                    f"平稳漂移：强势方Δp={_fmt_delta(euro_favored_prob_delta)} open_disp={_fmt_prob(euro_open.dispersion)}"
                )
                signal_bucket = "close"
                classified = True

            if not classified:
                if euro_dir == "support_favored" and abs((p_close or 0) - (p_open or 0)) >= 0.025:
                    prototype = "info_shock"
                    subclass = "info_shock_euro_first" if who_moves_first == "euro_first" else "info_shock_mvp"
                    action_type = "Risk" if mode == "shadow" else "Risk"
                    strength = "strong" if velocity_bucket == "fast" and euro_open.dispersion <= 0.06 else "medium"
                    direction_hint = "倾向顺强势方" if favored in {"home", "away"} else ""
                    if favored == "home":
                        prediction_bias = "胜"
                    elif favored == "away":
                        prediction_bias = "负"
                    why_parts.append(
                        f"信息冲击：强势方Δp={_fmt_delta(euro_favored_prob_delta)} 先动={who_moves_first} 速度={velocity_bucket}"
                    )
                    signal_bucket = "T-6" if euro_mid is not None else "open"
                else:
                    prototype = "risk_balancing"
                    subclass = "drift"
                    action_type = "Risk"
                    strength = "weak"
                    prediction_bias = ""
                    why_parts.append(f"弱信号漂移：强势方Δp={_fmt_delta(euro_favored_prob_delta)}")
                    signal_bucket = "close"

        features = MatchFeatures(
            prototype=prototype,
            subclass=subclass,
            favored_side=favored,
            euro_favored_prob_delta=euro_favored_prob_delta,
            draw_prob_delta=draw_prob_delta,
            dispersion_open=float(euro_open.dispersion) if euro_open is not None else None,
            dispersion_close=float(euro_close.dispersion) if euro_close is not None else None,
            convergence_flag=convergence_flag,
            who_moves_first=who_moves_first,
            velocity=velocity_bucket,
            ah_line_cross=ah_line_cross,
            ah_price_swing=ah_price_swing,
            reversal_flag=head_fake,
        )

        cfg_override = select_best_subclass(self._subclass_cfg, features)
        if cfg_override is not None:
            subclass = cfg_override.subclass_id
            prototype = cfg_override.prototype or prototype

        bias_mode = str(os.getenv("V2_PREDICTION_BIAS_MODE") or "A").strip().upper() or "A"
        if bias_mode == "B" and not prediction_bias:
            try:
                bias_params = load_v2_prediction_bias_params(
                    league=league_name,
                    dispersion_close=float(euro_close.dispersion) if euro_close and euro_close.dispersion is not None else None,
                )
                hint = str(direction_hint or "")
                if "防平" in hint:
                    prediction_bias = "平"
                elif any(k in hint for k in ["防冷", "谨慎", "避免单挑", "不单挑", "不建议单选"]):
                    if favored == "home":
                        prediction_bias = "平负"
                    elif favored == "away":
                        prediction_bias = "胜平"
                if not prediction_bias and action_type == "Risk":
                    p_draw_close = euro_close.p_draw

                    draw_tendency = "none"
                    if (
                        draw_dom_delta is not None
                        and abs(draw_dom_delta) >= bias_params.lean_draw.draw_dom_delta_abs_min
                        and euro_close.dispersion is not None
                        and euro_close.dispersion <= bias_params.lean_draw.close_dispersion_max
                    ):
                        draw_tendency = "lean"
                    elif (
                        draw_prob_delta is not None
                        and p_draw_close is not None
                        and draw_prob_delta >= bias_params.lean_draw.draw_prob_delta_min
                        and p_draw_close >= bias_params.lean_draw.p_draw_close_min
                        and euro_favored_prob_delta is not None
                        and euro_favored_prob_delta <= bias_params.lean_draw.favored_prob_delta_max
                        and euro_close.dispersion is not None
                        and euro_close.dispersion <= bias_params.lean_draw.close_dispersion_max
                    ):
                        draw_tendency = "lean"
                    elif (
                        draw_prob_delta is not None
                        and euro_favored_prob_delta is not None
                        and draw_prob_delta >= bias_params.guard_draw.draw_prob_delta_min
                        and euro_favored_prob_delta <= bias_params.guard_draw.favored_prob_delta_max
                    ):
                        draw_tendency = "guard"

                    draw_squeeze = False
                    if draw_prob_delta is not None and draw_prob_delta <= bias_params.two_heads.draw_prob_delta_max:
                        draw_squeeze = True
                    if p_draw_close is not None and p_draw_close <= bias_params.two_heads.p_draw_close_max:
                        draw_squeeze = True

                    if draw_tendency == "lean":
                        prediction_bias = "平"
                        why_parts.append("bias_fill:lean_draw")
                    elif draw_squeeze:
                        prediction_bias = "胜负"
                        why_parts.append("bias_fill:two_heads")
                    elif draw_tendency == "guard" and favored in {"home", "away"}:
                        prediction_bias = "平负" if favored == "home" else "胜平"
                        why_parts.append("bias_fill:guard_draw")
                    elif euro_dir == "fade_favored" and favored in {"home", "away"}:
                        prediction_bias = "平负" if favored == "home" else "胜平"
                        why_parts.append("bias_fill:fade_favored")
                    elif euro_dir == "support_favored" and favored in {"home", "away"}:
                        prediction_bias = "胜平" if favored == "home" else "平负"
                        why_parts.append("bias_fill:support_favored")
            except Exception:
                pass

        if convergence_flag:
            why_parts.append("convergence=strong")

        why = "；".join([p for p in why_parts if p])

        status = None
        cfg = self._subclass_cfg.get(subclass)
        if cfg:
            action_type = cfg.default_action
            if cfg.veto_tags:
                veto_tags = []
                league_name = str(match_data.get("league") or "")
                if "杯" in league_name or "欧冠" in league_name or "欧联" in league_name or "欧协" in league_name:
                    veto_tags.append("cup_match_volatility")
                if veto_tags:
                    action_type = "Risk" if action_type != "Diagnosis" else action_type
            else:
                veto_tags = []

            try:
                db = self._db or Database()
                metric = db.fetch_v2_monitor_metric(
                    subclass=subclass,
                    league=league_name,
                    regime="default",
                    window_name="mid",
                )
                if self._db is None:
                    db.close()
                status = getattr(metric, "status", None) if metric else None
            except Exception:
                status = None

            if status == "black":
                action_type = "Diagnosis"
            elif status == "white" and cfg.allow_direction and mode == "v2_full":
                if action_type != "Diagnosis" and strength in {"medium", "strong"} and direction_hint and not veto_tags:
                    action_type = "Direction"
        else:
            veto_tags = []

        decision = self._build_nspf_decision(
            league=league_name,
            favored=favored,
            subclass=subclass,
            action_type=action_type,
            strength=strength,
            prediction_bias=prediction_bias,
            direction_hint=direction_hint,
            dispersion=float(euro_open.dispersion) if euro_open is not None else None,
            status=status,
            euro_close=euro_close,
            euro_favored_prob_delta=euro_favored_prob_delta,
            draw_prob_delta=draw_prob_delta,
        )

        clv_prob = None
        clv_logit = None
        if p_open is not None and p_close is not None:
            if signal_bucket == "open":
                p_signal = p_open
            elif signal_bucket == "T-6" and p_mid is not None:
                p_signal = p_mid
            else:
                p_signal = p_open
            clv_prob = p_close - p_signal
            if 0.0001 < p_signal < 0.9999 and 0.0001 < p_close < 0.9999:
                import math

                clv_logit = math.log(p_close / (1 - p_close)) - math.log(p_signal / (1 - p_signal))

        dispersion = float(euro_open.dispersion) if euro_open is not None else None

        return MarketScriptV2Output(
            fixture_id=fixture_id,
            prediction_period=prediction_period,
            league=league_name,
            mode=mode,
            engine_version=self.ENGINE_VERSION,
            prototype=prototype,
            subclass=subclass,
            action_type=action_type,
            strength=strength,
            prediction_bias=prediction_bias,
            direction_hint=direction_hint,
            why=why,
            veto_tags=veto_tags,
            signal_bucket=signal_bucket,
            clv_prob=clv_prob,
            clv_logit=clv_logit,
            dispersion=dispersion,
            nspf_top1=str(decision.get("top1") or ""),
            nspf_cover=str(decision.get("cover") or ""),
            nspf_confidence=decision.get("confidence"),
            nspf_scores=decision.get("scores"),
            decision_reason=str(decision.get("reason") or ""),
            feedback_tag=str(decision.get("feedback_tag") or ""),
            upset_alert_level=str((decision.get("upset_alert") or {}).get("level") or ""),
            upset_alert_score=(decision.get("upset_alert") or {}).get("score"),
            upset_direction=str((decision.get("upset_alert") or {}).get("direction") or ""),
            upset_reasons=(decision.get("upset_alert") or {}).get("reasons") or [],
            upset_guard_pick=str((decision.get("upset_alert") or {}).get("guard_pick") or ""),
            created_at=now,
        )
