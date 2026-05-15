from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from src.market_script_v2.engine import MarketScriptV2Engine
from src.market_script_v2.features.euro import (
    EuroConsensus,
    build_euro_book_snapshot,
    consensus_from_books,
    implied_probs,
)
from src.db.database import Database


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _float_or_none(x: Any) -> Optional[float]:
    try:
        v = float(str(x).strip())
        if v != v:
            return None
        return v
    except Exception:
        return None

def _build_fixture_snapshots(
    *,
    fixture_id: str,
    kickoff: datetime,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    open_time = kickoff - timedelta(hours=72)
    t24_time = kickoff - timedelta(hours=24)
    close_time = kickoff - timedelta(minutes=30)

    out: List[Dict[str, Any]] = []
    for r in rows:
        company = str(r.get("company") or "unknown").strip() or "unknown"
        init_odds = (str(r.get("init_home") or ""), str(r.get("init_draw") or ""), str(r.get("init_away") or ""))
        live_odds = (str(r.get("live_home") or ""), str(r.get("live_draw") or ""), str(r.get("live_away") or ""))
        if implied_probs(*init_odds) is None or implied_probs(*live_odds) is None:
            continue
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": company,
                "snapshot_time": open_time,
                "odds_h": init_odds[0],
                "odds_d": init_odds[1],
                "odds_a": init_odds[2],
                "quality_flag": 0,
            }
        )
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": company,
                "snapshot_time": t24_time,
                "odds_h": init_odds[0],
                "odds_d": init_odds[1],
                "odds_a": init_odds[2],
                "quality_flag": 0,
            }
        )
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": company,
                "snapshot_time": close_time,
                "odds_h": live_odds[0],
                "odds_d": live_odds[1],
                "odds_a": live_odds[2],
                "quality_flag": 0,
            }
        )
    out.sort(key=lambda x: x["snapshot_time"])
    return out


def _favored_side_from_open(snapshots: List[Dict[str, Any]]) -> str:
    open_time = snapshots[0]["snapshot_time"] if snapshots else None
    if open_time is None:
        return "none"
    open_rows = [s for s in snapshots if s.get("snapshot_time") == open_time]
    books = [build_euro_book_snapshot(r) for r in open_rows]
    books = [b for b in books if b is not None]
    if not books:
        return "none"
    cons: EuroConsensus = consensus_from_books(books)
    return cons.favored_side()


def _calc_euro_deltas(snapshots: List[Dict[str, Any]]):
    if not snapshots:
        return None, None
    open_time = snapshots[0]["snapshot_time"]
    close_time = snapshots[-1]["snapshot_time"]
    open_rows = [s for s in snapshots if s.get("snapshot_time") == open_time]
    close_rows = [s for s in snapshots if s.get("snapshot_time") == close_time]
    open_books = [build_euro_book_snapshot(r) for r in open_rows]
    close_books = [build_euro_book_snapshot(r) for r in close_rows]
    open_books = [b for b in open_books if b is not None]
    close_books = [b for b in close_books if b is not None]
    if not open_books or not close_books:
        return None, None
    open_cons: EuroConsensus = consensus_from_books(open_books)
    close_cons: EuroConsensus = consensus_from_books(close_books)
    favored = open_cons.favored_side()
    favored_delta = None
    if favored == "home":
        favored_delta = (close_cons.p_home - open_cons.p_home) if (close_cons.p_home is not None and open_cons.p_home is not None) else None
    elif favored == "away":
        favored_delta = (close_cons.p_away - open_cons.p_away) if (close_cons.p_away is not None and open_cons.p_away is not None) else None
    draw_delta = (close_cons.p_draw - open_cons.p_draw) if (close_cons.p_draw is not None and open_cons.p_draw is not None) else None
    return favored_delta, draw_delta


class _FixtureDB:
    def __init__(
        self,
        euro_rows_by_fixture: Dict[str, List[Dict[str, Any]]],
        ah_rows_by_fixture: Dict[str, List[Dict[str, Any]]],
    ):
        self._euro_rows_by_fixture = euro_rows_by_fixture
        self._ah_rows_by_fixture = ah_rows_by_fixture

    def fetch_v2_odds_snapshots(self, fixture_id: str):
        return list(self._euro_rows_by_fixture.get(str(fixture_id), []))

    def fetch_v2_ah_snapshots(self, fixture_id: str):
        return list(self._ah_rows_by_fixture.get(str(fixture_id), []))

    def save_v2_script_output(self, output):
        return None

    def close(self):
        return None


def _load_euro_odds_history(
    *,
    db_path: str,
    since: Optional[str],
    until: Optional[str],
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where = ["fixture_id IS NOT NULL", "TRIM(fixture_id) != ''"]
    params: List[Any] = []
    if since:
        where.append("match_time >= ?")
        params.append(since)
    if until:
        where.append("match_time <= ?")
        params.append(until)

    sql = "SELECT fixture_id, league, match_time, company, init_home, init_draw, init_away, live_home, live_draw, live_away, actual_score, actual_result FROM euro_odds_history"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY match_time DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

    rows = [dict(r) for r in cur.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _parse_ah_triplet(text: Any) -> Optional[Tuple[str, str, str]]:
    s = str(text or "").strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split("|")]
    if len(parts) != 3:
        return None
    def _clean_price(x: str) -> str:
        return (
            x.replace("↑", "")
            .replace("↓", "")
            .replace("升", "")
            .replace("降", "")
            .replace(" ", "")
            .strip()
        )

    price_home = _clean_price(parts[0])
    ah_line = parts[1].replace(" ", "").replace("升", "").replace("降", "").strip()
    price_away = _clean_price(parts[2])
    if not price_home or not ah_line or not price_away:
        return None
    return price_home, ah_line, price_away


def _load_latest_match_raw_data_by_fixture(db_path: str, fixture_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not fixture_ids:
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(fixture_ids))
    sql = (
        f"SELECT fixture_id, raw_data, created_at FROM match_predictions "
        f"WHERE raw_data IS NOT NULL AND fixture_id IN ({placeholders}) "
        f"ORDER BY created_at DESC"
    )
    out: Dict[str, Dict[str, Any]] = {}
    for r in cur.execute(sql, fixture_ids).fetchall():
        fid = str(r["fixture_id"] or "").strip()
        if not fid or fid in out:
            continue
        raw_text = r["raw_data"]
        try:
            out[fid] = json.loads(raw_text) if isinstance(raw_text, str) else dict(raw_text)
        except Exception:
            continue
    conn.close()
    return out


def _load_actual_result_by_fixture(db_path: str, fixture_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not fixture_ids:
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(fixture_ids))
    sql = (
        f"SELECT fixture_id, actual_result, actual_score, match_time, updated_at, created_at "
        f"FROM match_predictions WHERE fixture_id IN ({placeholders}) "
        f"ORDER BY COALESCE(updated_at, created_at) DESC"
    )
    out: Dict[str, Dict[str, Any]] = {}
    for r in cur.execute(sql, fixture_ids).fetchall():
        fid = str(r["fixture_id"] or "").strip()
        if not fid or fid in out:
            continue
        out[fid] = {
            "actual_result": str(r["actual_result"] or "").strip() or None,
            "actual_score": str(r["actual_score"] or "").strip() or None,
            "match_time": r["match_time"],
        }
    conn.close()
    return out


def _build_ah_snapshots_from_raw(*, fixture_id: str, kickoff: datetime, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    asian_odds = raw.get("asian_odds") if isinstance(raw, dict) else None
    if not isinstance(asian_odds, dict):
        return []
    open_time = kickoff - timedelta(hours=72)
    t24_time = kickoff - timedelta(hours=24)
    close_time = kickoff - timedelta(minutes=30)

    out: List[Dict[str, Any]] = []
    for book_id, item in asian_odds.items():
        if not isinstance(item, dict):
            continue
        start = _parse_ah_triplet(item.get("start"))
        live = _parse_ah_triplet(item.get("live"))
        if start is None or live is None:
            continue
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": str(book_id),
                "snapshot_time": open_time,
                "ah_line": start[1],
                "price_home": start[0],
                "price_away": start[2],
                "is_mainline": True,
                "quality_flag": 0,
            }
        )
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": str(book_id),
                "snapshot_time": t24_time,
                "ah_line": start[1],
                "price_home": start[0],
                "price_away": start[2],
                "is_mainline": True,
                "quality_flag": 0,
            }
        )
        out.append(
            {
                "fixture_id": fixture_id,
                "book_id": str(book_id),
                "snapshot_time": close_time,
                "ah_line": live[1],
                "price_home": live[0],
                "price_away": live[2],
                "is_mainline": True,
                "quality_flag": 0,
            }
        )
    out.sort(key=lambda x: x["snapshot_time"])
    return out


def _normalize_actual_result(actual_result: Any, actual_score: Any) -> Optional[str]:
    r = str(actual_result or "").strip()
    if r in {"胜", "平", "负"}:
        return r
    score = str(actual_score or "").strip()
    if not score:
        return None
    import re

    m = re.search(r"(\d+)\s*[:：-]\s*(\d+)", score)
    if not m:
        return None
    hs = int(m.group(1))
    as_ = int(m.group(2))
    if hs > as_:
        return "胜"
    if hs < as_:
        return "负"
    return "平"


def run_backtest(
    *,
    db_path: str,
    since: Optional[str],
    until: Optional[str],
    limit: Optional[int],
    min_books: int,
    out_prefix: str,
    bias_mode: str,
) -> Tuple[str, str]:
    bias_mode = str(bias_mode or "A").strip().upper() or "A"
    os.environ["V2_PREDICTION_BIAS_MODE"] = bias_mode
    rows = _load_euro_odds_history(db_path=db_path, since=since, until=until, limit=limit)

    by_fixture: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    fixture_meta: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        fixture_id = str(r.get("fixture_id") or "").strip()
        if not fixture_id:
            continue
        kickoff = _parse_dt(r.get("match_time"))
        if kickoff is None:
            continue
        fixture_meta.setdefault(
            fixture_id,
            {
                "fixture_id": fixture_id,
                "league": str(r.get("league") or ""),
                "kickoff": kickoff,
                "actual_result": _normalize_actual_result(r.get("actual_result"), r.get("actual_score")),
                "actual_score": str(r.get("actual_score") or ""),
            },
        )
        by_fixture[fixture_id].append(r)

    euro_rows_by_fixture: Dict[str, List[Dict[str, Any]]] = {}
    ah_rows_by_fixture: Dict[str, List[Dict[str, Any]]] = {}
    eval_rows: List[Dict[str, Any]] = []
    skipped = 0
    for fixture_id, fixture_rows in by_fixture.items():
        meta = fixture_meta.get(fixture_id)
        if not meta:
            skipped += 1
            continue
        kickoff = meta["kickoff"]

        books = 0
        usable_rows = []
        for r in fixture_rows:
            init_odds = (r.get("init_home"), r.get("init_draw"), r.get("init_away"))
            live_odds = (r.get("live_home"), r.get("live_draw"), r.get("live_away"))
            if implied_probs(*init_odds) is None or implied_probs(*live_odds) is None:
                continue
            books += 1
            usable_rows.append(r)
        if books < int(min_books):
            skipped += 1
            continue

        snapshots = _build_fixture_snapshots(fixture_id=fixture_id, kickoff=kickoff, rows=usable_rows)
        if len(snapshots) < 3:
            skipped += 1
            continue
        euro_rows_by_fixture[fixture_id] = snapshots

    raw_by_fixture = _load_latest_match_raw_data_by_fixture(db_path, list(euro_rows_by_fixture.keys()))
    actual_by_fixture = _load_actual_result_by_fixture(db_path, list(euro_rows_by_fixture.keys()))
    for fixture_id, meta in fixture_meta.items():
        if fixture_id not in euro_rows_by_fixture:
            continue
        kickoff = meta.get("kickoff")
        if not isinstance(kickoff, datetime):
            continue
        raw = raw_by_fixture.get(fixture_id)
        if not isinstance(raw, dict):
            continue
        ah_rows = _build_ah_snapshots_from_raw(fixture_id=fixture_id, kickoff=kickoff, raw=raw)
        if ah_rows:
            ah_rows_by_fixture[fixture_id] = ah_rows

        if not meta.get("actual_result"):
            alt = actual_by_fixture.get(fixture_id) or {}
            meta["actual_result"] = _normalize_actual_result(alt.get("actual_result"), alt.get("actual_score"))
            if not meta.get("actual_score"):
                meta["actual_score"] = str(alt.get("actual_score") or "")

    db = _FixtureDB(euro_rows_by_fixture, ah_rows_by_fixture)
    engine = MarketScriptV2Engine(db=db)

    for fixture_id, snapshots in euro_rows_by_fixture.items():
        meta = fixture_meta.get(fixture_id) or {}
        kickoff = meta.get("kickoff")
        league = str(meta.get("league") or "")

        match_data = {"match_time": kickoff, "league": league}
        out = engine._analyze_core(
            fixture_id=fixture_id,
            prediction_period="final",
            match_data=match_data,
            mode="shadow",
        )
        favored_side = _favored_side_from_open(snapshots)
        euro_favored_prob_delta, draw_prob_delta = _calc_euro_deltas(snapshots)
        actual_result = meta.get("actual_result")
        favored_win = None
        if favored_side == "home" and actual_result in {"胜", "平", "负"}:
            favored_win = actual_result == "胜"
        elif favored_side == "away" and actual_result in {"胜", "平", "负"}:
            favored_win = actual_result == "负"

        eval_rows.append(
            {
                "fixture_id": fixture_id,
                "league": league,
                "kickoff": kickoff.isoformat(sep=" ") if isinstance(kickoff, datetime) else "",
                "prototype": out.prototype,
                "subclass": out.subclass,
                "action_type": out.action_type,
                "strength": out.strength,
                "prediction_bias": getattr(out, "prediction_bias", ""),
                "signal_bucket": out.signal_bucket,
                "clv_prob": out.clv_prob,
                "clv_logit": out.clv_logit,
                "dispersion": out.dispersion,
                "euro_favored_prob_delta": euro_favored_prob_delta,
                "draw_prob_delta": draw_prob_delta,
                "favored_side": favored_side,
                "actual_result": actual_result,
                "favored_win": favored_win,
                "why": out.why,
            }
        )

    total = len(by_fixture)
    evaluated = len(eval_rows)

    def _clv_pos(x: Any) -> Optional[bool]:
        v = _float_or_none(x)
        if v is None:
            return None
        return v > 0

    baseline = [r for r in eval_rows if r.get("favored_win") is not None]
    baseline_win_rate = (sum(1 for r in baseline if r.get("favored_win")) / len(baseline)) if baseline else None

    bias_non_empty = [r for r in eval_rows if str(r.get("prediction_bias") or "").strip()]
    bias_non_empty_rate = (len(bias_non_empty) / len(eval_rows)) if eval_rows else None
    bias_draw_covered = [r for r in eval_rows if "平" in str(r.get("prediction_bias") or "")]
    bias_draw_covered_rate = (len(bias_draw_covered) / len(eval_rows)) if eval_rows else None

    by_subclass: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in eval_rows:
        by_subclass[str(r.get("subclass") or "")].append(r)

    summary_rows = []
    for subclass, items in by_subclass.items():
        clv_vals = [
            _float_or_none(x.get("clv_prob"))
            for x in items
            if _float_or_none(x.get("clv_prob")) is not None
        ]
        clv_pos = [
            _clv_pos(x.get("clv_prob"))
            for x in items
            if _clv_pos(x.get("clv_prob")) is not None
        ]
        fw = [x for x in items if x.get("favored_win") is not None]
        win_rate = (sum(1 for x in fw if x.get("favored_win")) / len(fw)) if fw else None

        action_counts = defaultdict(int)
        for x in items:
            action_counts[str(x.get("action_type") or "")] += 1
        action_type = max(action_counts.keys(), key=lambda k: action_counts[k]) if action_counts else ""

        lift = (win_rate - baseline_win_rate) if (win_rate is not None and baseline_win_rate is not None) else None
        risk_effect = (baseline_win_rate - win_rate) if (win_rate is not None and baseline_win_rate is not None) else None
        summary_rows.append(
            {
                "subclass": subclass,
                "prototype": str(items[0].get("prototype") or ""),
                "action_type": action_type,
                "n": len(items),
                "clv_rate": (sum(1 for x in clv_pos if x) / len(clv_pos)) if clv_pos else None,
                "clv_mean": (sum(clv_vals) / len(clv_vals)) if clv_vals else None,
                "favored_win_rate": win_rate,
                "lift_vs_baseline": lift,
                "risk_effect": risk_effect,
            }
        )

    summary_rows.sort(key=lambda r: (r.get("n") or 0, _float_or_none(r.get("clv_mean")) or -999.0), reverse=True)

    stamp = datetime.now().strftime("%Y-%m-%d")
    out_json = f"{out_prefix}_{bias_mode}_{stamp}.json"
    out_md = f"{out_prefix}_{bias_mode}_{stamp}.md"

    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "meta": {
                    "db_path": db_path,
                    "since": since,
                    "until": until,
                    "limit": limit,
                    "min_books": min_books,
                    "total_fixtures": total,
                    "evaluated": evaluated,
                    "skipped": skipped,
                    "fixtures_with_ah": len(ah_rows_by_fixture),
                    "baseline_favored_win_rate": baseline_win_rate,
                    "bias_non_empty_rate": bias_non_empty_rate,
                    "bias_draw_covered_rate": bias_draw_covered_rate,
                },
                "summary_by_subclass": summary_rows,
                "rows": eval_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    def _fmt_pct(x: Optional[float]) -> str:
        if x is None:
            return "-"
        return f"{x*100:.1f}%"

    def _fmt_f(x: Optional[float]) -> str:
        if x is None:
            return "-"
        return f"{x:.4f}"

    lines = []
    lines.append(f"# v2 历史回测（欧赔 init/live 合成 3 桶）\n")
    lines.append(f"- prediction_bias 模式：{os.environ.get('V2_PREDICTION_BIAS_MODE')}")
    lines.append(f"- 数据源：`{db_path}` / `euro_odds_history`")
    lines.append(f"- 赛程过滤：since={since or '-'}，until={until or '-'}，limit={limit or '-'}")
    lines.append(f"- 最少公司数：{min_books}")
    lines.append(f"- 总 fixture：{total}，可评估：{evaluated}，跳过：{skipped}")
    lines.append(f"- 有亚盘快照（来自 match_predictions.raw_data）：{len(ah_rows_by_fixture)}")
    lines.append(f"- baseline（open favored 胜率）：{_fmt_pct(baseline_win_rate)}\n")
    lines.append(f"- v2 预测偏向覆盖率：{_fmt_pct(bias_non_empty_rate)}（prediction_bias 非空）")
    lines.append(f"- v2 平局覆盖率：{_fmt_pct(bias_draw_covered_rate)}（prediction_bias 含“平”）\n")

    lines.append("## 子类汇总（按样本量排序）\n")
    lines.append("| subclass | prototype | action | n | CLV+率 | 平均CLV_prob | favored胜率 | vs baseline |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for r in summary_rows[:40]:
        lift = _float_or_none(r.get("lift_vs_baseline"))
        lift_txt = _fmt_pct(lift) if lift is not None else "-"
        lines.append(
            f"| {r['subclass']} | {r['prototype']} | {r.get('action_type') or ''} | {r['n']} | {_fmt_pct(r.get('clv_rate'))} | {_fmt_f(_float_or_none(r.get('clv_mean')))} | {_fmt_pct(r.get('favored_win_rate'))} | {lift_txt} |"
        )

    eligible = [
        r
        for r in summary_rows
        if (r.get("n") or 0) >= 20 and (_float_or_none(r.get("clv_mean")) is not None)
    ]
    eligible.sort(key=lambda r: _float_or_none(r.get("clv_mean")) or -999.0, reverse=True)
    lines.append("\n## 子类汇总（按平均CLV_prob排序，n>=20）\n")
    lines.append("| subclass | prototype | action | n | CLV+率 | 平均CLV_prob | favored胜率 | vs baseline |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for r in eligible[:25]:
        lift = _float_or_none(r.get("lift_vs_baseline"))
        lift_txt = _fmt_pct(lift) if lift is not None else "-"
        lines.append(
            f"| {r['subclass']} | {r['prototype']} | {r.get('action_type') or ''} | {r['n']} | {_fmt_pct(r.get('clv_rate'))} | {_fmt_f(_float_or_none(r.get('clv_mean')))} | {_fmt_pct(r.get('favored_win_rate'))} | {lift_txt} |"
        )

    risk_rank = [r for r in summary_rows if (r.get("n") or 0) >= 20 and (r.get("action_type") in {"Risk"})]
    risk_rank.sort(key=lambda r: _float_or_none(r.get("risk_effect")) or -999.0, reverse=True)
    lines.append("\n## Risk 子类：降低热门胜率效果（baseline - favored胜率，n>=20）\n")
    lines.append("| subclass | prototype | n | 风险效果 | favored胜率 | baseline |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for r in risk_rank[:25]:
        eff = _float_or_none(r.get("risk_effect"))
        eff_txt = _fmt_pct(eff) if eff is not None else "-"
        lines.append(
            f"| {r['subclass']} | {r['prototype']} | {r['n']} | {eff_txt} | {_fmt_pct(r.get('favored_win_rate'))} | {_fmt_pct(baseline_win_rate)} |"
        )

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    try:
        db = Database()
        run_id = db.create_v2_backtest_run(
            run_tag=f"historical_{bias_mode}",
            since=since,
            until=until,
            limit=limit,
            min_books=min_books,
            total_fixtures=total,
            evaluated=evaluated,
            skipped=skipped,
            fixtures_with_ah=len(ah_rows_by_fixture),
        )
        db.bulk_insert_v2_backtest_rows(run_id, eval_rows)
        db.close()
    except Exception:
        pass

    return out_md, out_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.path.join("data", "football.db"))
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-books", type=int, default=5)
    parser.add_argument("--bias-mode", default="A", choices=["A", "B", "a", "b"])
    parser.add_argument("--out-prefix", default=os.path.join("data", "reports", "v2_historical_backtest"))
    args = parser.parse_args()

    out_md, out_json = run_backtest(
        db_path=str(args.db),
        since=args.since,
        until=args.until,
        limit=args.limit,
        min_books=int(args.min_books),
        out_prefix=str(args.out_prefix),
        bias_mode=str(args.bias_mode),
    )
    print(out_md)
    print(out_json)


if __name__ == "__main__":
    main()
