import base64
from datetime import date, datetime, time, timedelta
import os
import sys
import time as _time
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.constants import AUTH_TOKEN_TTL
from src.db.database import Database
from src.market_script_v2.features.time_buckets import bucket_by_kickoff
from src.market_script_v2.features.euro import build_euro_book_snapshot, consensus_from_books, dominant_shift
from src.market_script_v2.engine import MarketScriptV2Engine
from src.llm.predictor import LLMPredictor
from src.crawler.odds_crawler import OddsCrawler
from src.market_script_v2.daily_window import compute_today_window
from src.utils.nspf_summary import (
    build_pick_summary,
    clean_prediction_result_text,
    extract_nspf_tokens,
    extract_report_nspf_cover,
    primary_token_from_display,
)
from scripts.v2_daily_collect_snapshots import collect_snapshots_for_window
from src.crawler.jingcai_crawler import JingcaiCrawler
from scripts.v2_daily_postmortem import update_results_for_target_date, generate_daily_report
from scripts.v2_feedback_optimizer import optimize_feedback


def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode("utf-8")).decode("utf-8")
        username, timestamp = raw.split("|")
        return username, int(timestamp)
    except Exception:
        return None, 0


if "auth" in st.query_params and not st.session_state.get("logged_in", False):
    try:
        token = st.query_params["auth"]
        username, login_timestamp = decode_auth_token(token)
        if username and (int(_time.time()) - login_timestamp <= AUTH_TOKEN_TTL):
            db = Database()
            user = db.get_user(username)
            db.close()
            if user and datetime.now() <= user.valid_until:
                st.session_state["logged_in"] = True
                st.session_state["username"] = user.username
                st.session_state["role"] = user.role
                st.session_state["valid_until"] = user.valid_until
                st.session_state["auth_token"] = token
    except Exception:
        pass

if not st.session_state.get("logged_in", False):
    st.warning("⚠️ 您尚未登录或会话已过期，请先登录！")
    if st.button("👉 返回登录页面"):
        st.switch_page("app.py")
    st.stop()

if "auth" not in st.query_params:
    token = st.session_state.get("auth_token", "")
    if not token and st.session_state.get("username"):
        try:
            raw_token = f"{st.session_state['username']}|{int(_time.time())}"
            token = base64.b64encode(raw_token.encode("utf-8")).decode("utf-8")
        except Exception:
            token = ""
    if token:
        st.session_state["auth_token"] = token
        st.query_params["auth"] = token

st.set_page_config(page_title="v2 执行监控", page_icon="⚽", layout="wide")
st.markdown(
    """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _window_from_day(d: date):
    start = datetime.combine(d, time(12, 0, 0))
    end = start + timedelta(days=1)
    tag = start.strftime("%Y-%m-%d_12")
    return start, end, tag


def _fmt_dt(dt: object) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%m-%d %H:%M")
    return "-"


def _tokens_from_text(text: str) -> List[str]:
    return extract_nspf_tokens(text)


def _badge(text: str, status: str):
    color = {
        "ok": "#22C55E",
        "warn": "#F59E0B",
        "bad": "#EF4444",
        "muted": "#9FB0C3",
    }.get(status, "#9FB0C3")
    st.markdown(
        f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;background:{color}22;border:1px solid {color}55;color:{color};font-size:12px;'>"
        f"{text}</span>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=30)
def _load_window_data(window_tag: str):
    db = Database()
    fixtures = db.fetch_v2_daily_fixtures(window_tag)
    fixture_ids = [str(x.get("fixture_id") or "") for x in fixtures if x.get("fixture_id")]
    snap_stats = db.fetch_v2_snapshot_stats_for_fixtures(fixture_ids)
    preds = db.fetch_latest_predictions_for_fixtures(fixture_ids, prediction_period="final")
    v2 = db.fetch_latest_v2_script_output_for_fixtures(fixture_ids, prediction_period="final")
    db.close()
    return fixtures, snap_stats, preds, v2


def _compute_bucket_counts(db: Database, fixture_id: str, kickoff: Optional[datetime]):
    euro_rows = db.fetch_v2_odds_snapshots(fixture_id)
    euro_bucketed = bucket_by_kickoff(euro_rows, kickoff)
    counts = euro_bucketed.bucket_counts()
    present = sum(1 for v in counts.values() if v > 0)
    first_time = None
    last_time = None
    if euro_rows:
        euro_rows_sorted = sorted([r for r in euro_rows if r.get("snapshot_time")], key=lambda r: r["snapshot_time"])
        if euro_rows_sorted:
            first_time = euro_rows_sorted[0]["snapshot_time"]
            last_time = euro_rows_sorted[-1]["snapshot_time"]
    return counts, present, first_time, last_time


def _timeline_line(title: str, status: str, dt: object, detail: str = ""):
    icon = {
        "ok": "✅",
        "warn": "⚠️",
        "bad": "⛔",
        "muted": "·",
    }.get(status, "·")
    suffix = f"（{detail}）" if detail else ""
    st.write(f"{icon} {title}：{_fmt_dt(dt)}{suffix}")


def _cn_action(action: str) -> str:
    a = str(action or "").strip().lower()
    return {
        "direction": "方向",
        "risk": "风控",
        "diagnosis": "诊断",
    }.get(a, action or "")


def _cn_strength(strength: str) -> str:
    s = str(strength or "").strip().lower()
    return {
        "strong": "强",
        "medium": "中",
        "weak": "弱",
    }.get(s, strength or "")


def _cn_prototype(proto: str) -> str:
    p = str(proto or "").strip().lower()
    mapping = {
        "info_shock": "信息冲击",
        "risk_balancing": "风控平衡",
        "public_pressure": "大众热度",
        "head_fake": "试盘假动作",
        "cross_market_divergence": "欧亚背离",
        "draw_shaping": "平局定价",
        "key_number_mgmt": "关键档位管理",
        "late_correction": "临场纠偏",
        "insufficient_data": "数据不足",
    }
    return mapping.get(p, proto or "")


def _cn_subclass(sub: str) -> str:
    s = str(sub or "").strip().lower()
    mapping = {
        "info_shock_mvp": "信息冲击（MVP）",
        "info_shock_euro_first": "信息冲击（欧赔先动）",
        "risk_balancing_flat_drift": "风控平衡（平稳漂移）",
        "risk_balancing_price_only": "风控平衡（只动水不动盘）",
        "drift": "漂移",
        "high_dispersion": "高分歧（信号弱）",
        "public_pressure_popular_tax": "热门加税（防平/防冷）",
        "public_pressure_popular_deepening": "热门深盘引导（谨慎追热门）",
        "head_fake_v_reversal": "试盘假动作（回撤）",
        "divergence_euro_vs_ah": "欧亚背离（方向不一致）",
        "draw_shaping_draw_driven": "平局定价（平驱动）",
        "key_number_hold": "关键档位顶住（水位管理）",
        "late_correction_key_cross": "临场纠偏（跨档）",
        "late_correction_convergence": "临场纠偏（分歧收敛）",
        "insufficient_data": "数据不足",
    }
    return mapping.get(s, sub or "")


def _format_v2_cn(v2: Dict) -> str:
    if not v2:
        return ""
    bias = str(v2.get("prediction_bias") or "").strip()
    top1 = str(v2.get("nspf_top1") or "").strip()
    cover = str(v2.get("nspf_cover") or "").strip()
    conf = v2.get("nspf_confidence")
    upset_level = str(v2.get("upset_alert_level") or "").strip()
    upset_direction = str(v2.get("upset_direction") or "").strip()
    parts = [
        _cn_prototype(v2.get("prototype")),
        _cn_subclass(v2.get("subclass")),
        _cn_action(v2.get("action_type")),
        _cn_strength(v2.get("strength")),
    ]
    if bias:
        parts.append(f"预测偏向:{bias}")
    if top1:
        parts.append(f"主推:{top1}")
    if cover:
        parts.append(f"覆盖:{cover}")
    if conf is not None:
        parts.append(f"置信度:{conf}")
    if upset_level:
        parts.append(f"冷门警觉:{upset_level}")
    if upset_direction:
        parts.append(f"冷门方向:{upset_direction}")
    return " / ".join([p for p in parts if p])


def _prob_pct(p: object) -> str:
    try:
        if p is None:
            return "-"
        return f"{float(p) * 100:.1f}%"
    except Exception:
        return "-"


def _f4(x: object) -> str:
    try:
        if x is None:
            return "-"
        return f"{float(x):.4f}"
    except Exception:
        return "-"


def _build_euro_bucket_summary(euro_bucketed):
    rows = []
    for key, items in [
        ("open", euro_bucketed.open),
        ("T-24", euro_bucketed.t_24),
        ("T-12", euro_bucketed.t_12),
        ("T-6", euro_bucketed.t_6),
        ("T-1", euro_bucketed.t_1),
        ("close", euro_bucketed.close),
    ]:
        books = [build_euro_book_snapshot(r) for r in items]
        books = [b for b in books if b is not None]
        n_books = len({b.book_id for b in books})
        if books:
            cons = consensus_from_books(books)
            rows.append(
                {
                    "bucket": key,
                    "rows": len(items),
                    "books": n_books,
                    "p_home": cons.p_home,
                    "p_draw": cons.p_draw,
                    "p_away": cons.p_away,
                    "dispersion": cons.dispersion,
                }
            )
        else:
            rows.append(
                {
                    "bucket": key,
                    "rows": len(items),
                    "books": n_books,
                    "p_home": None,
                    "p_draw": None,
                    "p_away": None,
                    "dispersion": None,
                }
            )
    return rows


def _format_euro_summary_table(rows: List[Dict]):
    out = []
    for r in rows:
        out.append(
            {
                "时间桶": r["bucket"],
                "快照条数": r["rows"],
                "公司数": r["books"],
                "主胜概率": _prob_pct(r.get("p_home")),
                "平局概率": _prob_pct(r.get("p_draw")),
                "客胜概率": _prob_pct(r.get("p_away")),
                "分歧度": _f4(r.get("dispersion")),
            }
        )
    return out


def _summarize_ah_rows(ah_rows: List[Dict]):
    def _pick(rows: List[Dict], book_id: str):
        xs = [r for r in rows if str(r.get("book_id") or "") == book_id and r.get("snapshot_time")]
        xs = sorted(xs, key=lambda r: r["snapshot_time"])
        if not xs:
            return None
        first = xs[0]
        last = xs[-1]
        return {
            "book": book_id,
            "first_time": first.get("snapshot_time"),
            "first_line": first.get("ah_line"),
            "first_home": first.get("price_home"),
            "first_away": first.get("price_away"),
            "last_time": last.get("snapshot_time"),
            "last_line": last.get("ah_line"),
            "last_home": last.get("price_home"),
            "last_away": last.get("price_away"),
        }

    return [x for x in [_pick(ah_rows, "macau"), _pick(ah_rows, "bet365")] if x]


def _run_v2_for_fixture(db: Database, fixture_id: str, fixture: dict, prediction_period: str = "final"):
    engine = MarketScriptV2Engine(db=db)
    match_data = {
        "fixture_id": fixture_id,
        "league": fixture.get("league") or "",
        "match_time": fixture.get("kickoff_time"),
    }
    return engine.analyze(
        fixture_id=str(fixture_id),
        prediction_period=prediction_period,
        match_data=match_data,
        mode=(os.getenv("PREDICTION_MARKET_ENGINE_MODE") or "v2_full").strip().lower() or "v2_full",
    )


def _run_final_for_fixture(db: Database, fixture_id: str, fixture: dict):
    predictor = LLMPredictor()
    odds_crawler = OddsCrawler()
    details = odds_crawler.fetch_match_details(
        fixture_id,
        home_team=fixture.get("home_team"),
        away_team=fixture.get("away_team"),
    )
    match_data = {}
    match_data.update(
        {
            "fixture_id": fixture_id,
            "match_num": fixture.get("match_num"),
            "league": fixture.get("league"),
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "match_time": fixture.get("kickoff_time"),
        }
    )
    match_data.update(details or {})
    text = predictor.predict(match_data, period="final", total_matches_count=None, is_sfc=False)
    match_data["llm_prediction"] = text
    db.save_prediction(match_data, period="final")
    return True


def _lock_window_fixtures(window_start: datetime, window_end: datetime, window_tag: str) -> int:
    crawler = JingcaiCrawler()
    matches = crawler.fetch_matches_in_window(window_start, window_end)
    if not matches:
        return 0
    fixtures = []
    for m in matches:
        fixtures.append(
            {
                "fixture_id": m.get("fixture_id"),
                "match_num": m.get("match_num"),
                "league": m.get("league"),
                "home_team": m.get("home_team"),
                "away_team": m.get("away_team"),
                "kickoff_time": m.get("match_time"),
            }
        )
    db = Database()
    saved = db.upsert_v2_daily_fixtures(
        window_tag=window_tag,
        window_start=window_start,
        window_end=window_end,
        fixtures=fixtures,
        source="jingcai",
    )
    db.close()
    return saved


def _fetch_fixtures_for_window_tag(window_tag: str):
    try:
        db = Database()
        rows = db.fetch_v2_daily_fixtures(window_tag)
        db.close()
        return rows or []
    except Exception:
        return []


def _safe_read_text(path: str) -> str:
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        return ""
    return ""


def _parse_markdown_table(table_lines: List[str]) -> Optional[pd.DataFrame]:
    if len(table_lines) < 2:
        return None

    def _split_row(line: str) -> List[str]:
        raw = line.strip().strip("|")
        return [cell.strip() for cell in raw.split("|")]

    headers = _split_row(table_lines[0])
    rows = []
    for line in table_lines[2:]:
        cells = _split_row(line)
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        elif len(cells) > len(headers):
            cells = cells[: len(headers)]
        rows.append(cells)
    if not rows:
        return None
    return pd.DataFrame(rows, columns=headers)


def _parse_v2_daily_report(report_text: str) -> Dict[str, object]:
    metrics: Dict[str, str] = {}
    tables: Dict[str, pd.DataFrame] = {}
    current_section = "概览"
    lines = [str(line or "").rstrip() for line in (report_text or "").splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("- ") and "：" in line:
            key, value = line[2:].split("：", 1)
            metrics[key.strip()] = value.strip()
        elif line.startswith("## "):
            current_section = line[3:].strip()
        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|---"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            table = _parse_markdown_table(table_lines)
            if table is not None:
                tables[current_section] = table
            continue
        i += 1
    return {"metrics": metrics, "tables": tables}


def _style_rate_table(df: pd.DataFrame):
    def _style_value(value):
        text = str(value or "").strip()
        if not text.endswith("%"):
            return ""
        try:
            pct = float(text.rstrip("%"))
        except Exception:
            return ""
        if pct >= 80:
            return "font-weight:700;color:#166534;background-color:#DCFCE7;"
        if pct >= 60:
            return "font-weight:700;color:#92400E;background-color:#FEF3C7;"
        return "font-weight:700;color:#991B1B;background-color:#FEE2E2;"

    return df.style.map(_style_value)


def _style_single_match_table(df: pd.DataFrame):
    def _style_row(row):
        actual = str(row.get("实际") or "").strip()
        styles = []
        for col in row.index:
            value = str(row.get(col) or "").strip()
            style = ""
            if col == "实际":
                style = "font-weight:700;color:#111827;background-color:#E5E7EB;"
            elif col in {"程序覆盖", "最终覆盖"} and value:
                hit = bool(actual and actual in value)
                style = (
                    "font-weight:700;color:#166534;background-color:#DCFCE7;"
                    if hit
                    else "font-weight:700;color:#991B1B;background-color:#FEE2E2;"
                )
            elif col in {"程序Top1", "最终Top1", "基准"} and value:
                primary = primary_token_from_display(value)
                hit = bool(actual and primary and actual == primary)
                style = (
                    "font-weight:700;color:#166534;background-color:#DCFCE7;"
                    if hit
                    else "font-weight:700;color:#991B1B;background-color:#FEE2E2;"
                )
            styles.append(style)
        return pd.Series(styles, index=row.index)

    return df.style.apply(_style_row, axis=1)


def _render_v2_daily_report_preview(report_text: str):
    parsed = _parse_v2_daily_report(report_text)
    metrics = parsed.get("metrics") or {}
    tables = parsed.get("tables") or {}

    if metrics:
        ordered_keys = [
            "场次",
            "程序化覆盖命中率",
            "程序化Top1命中率",
            "最终文本覆盖命中率",
            "最终文本Top1命中率",
            "欧赔close基准命中率",
        ]
        metric_cols = st.columns(3)
        visible_items = [(k, metrics[k]) for k in ordered_keys if k in metrics]
        for idx, (key, value) in enumerate(visible_items):
            metric_cols[idx % 3].metric(key, value)

    if tables:
        section_order = ["单场明细", "子类表现", "偏向表现", "联赛子类表现"]
        for section_name in section_order:
            table = tables.get(section_name)
            if table is None:
                continue
            st.write(section_name)
            if section_name == "单场明细":
                st.dataframe(_style_single_match_table(table), use_container_width=True, hide_index=True)
            else:
                st.dataframe(_style_rate_table(table), use_container_width=True, hide_index=True)
    else:
        st.text_area("日报预览", report_text, height=260, disabled=True)


def _build_match_summary_df(rows: List[Dict]) -> pd.DataFrame:
    data = []
    for item in rows or []:
        matchup = f"{item.get('home') or '-'} vs {item.get('away') or '-'}"
        kickoff = item.get("kickoff")
        kickoff_text = kickoff.strftime("%m-%d %H:%M") if isinstance(kickoff, datetime) else str(kickoff or "")
        data.append(
            {
                "场次": str(item.get("match_num") or ""),
                "开赛": kickoff_text,
                "联赛": str(item.get("league") or ""),
                "对阵": matchup,
                "实际": str(item.get("actual") or ""),
                "程序覆盖": str(item.get("prog_cover") or ""),
                "程序Top1": str(item.get("prog_top1") or ""),
                "程序置信度": item.get("prog_confidence"),
                "最终覆盖": str(item.get("final_cover") or ""),
                "最终Top1": str(item.get("final_top1") or ""),
                "基准": str(item.get("baseline") or ""),
                "子类": str(item.get("subclass") or ""),
                "偏向": str(item.get("prediction_bias") or ""),
            }
        )
    return pd.DataFrame(data)


def _render_match_summary_table(rows: List[Dict]):
    df = _build_match_summary_df(rows)
    if df.empty:
        st.caption("当前日期暂无日报明细")
        return
    st.dataframe(_style_single_match_table(df), use_container_width=True, hide_index=True)


def _build_live_match_summary_df(fixtures: List[Dict], preds: Dict[str, Dict], v2_out: Dict[str, Dict]) -> pd.DataFrame:
    data = []
    for item in fixtures or []:
        fid = str(item.get("fixture_id") or "")
        pred = preds.get(fid) or {}
        v2 = v2_out.get(fid) or {}
        kickoff = item.get("kickoff_time")
        kickoff_text = kickoff.strftime("%m-%d %H:%M") if isinstance(kickoff, datetime) else str(kickoff or "")
        prediction_text = str(pred.get("prediction_text") or "").strip()
        prog_summary = build_pick_summary(
            cover_text=str(v2.get("nspf_cover") or v2.get("nspf_top1") or ""),
            scores=v2.get("nspf_scores"),
            primary_token=str(v2.get("nspf_top1") or ""),
        )
        predicted_result_raw = str(pred.get("predicted_result") or "")
        cleaned_predicted_result = clean_prediction_result_text(predicted_result_raw)
        final_cover = extract_report_nspf_cover(prediction_text, predicted_result_raw)
        final_summary = build_pick_summary(
            cover_text=final_cover,
            scores=v2.get("nspf_scores"),
            primary_token=str(prog_summary.get("primary") or ""),
        )
        status = "未生成"
        if v2 and pred:
            status = "已生成"
        elif v2:
            status = "仅v2"
        elif pred:
            status = "仅final"

        if pred:
            prediction_result_display = cleaned_predicted_result or ("待解析" if prediction_text else "空报告")
            final_cover_display = str(final_summary.get("cover") or ("待解析" if prediction_text else "空报告"))
            final_top1_display = str(final_summary.get("display") or ("待解析" if prediction_text else "空报告"))
        else:
            prediction_result_display = "未生成"
            final_cover_display = "未生成"
            final_top1_display = "未生成"

        data.append(
            {
                "场次": str(item.get("match_num") or ""),
                "开赛": kickoff_text,
                "联赛": str(item.get("league") or ""),
                "对阵": f"{item.get('home_team') or '-'} vs {item.get('away_team') or '-'}",
                "执行状态": status,
                "程序覆盖": str(prog_summary.get("cover") or ""),
                "程序Top1": str(prog_summary.get("display") or ""),
                "程序置信度": v2.get("nspf_confidence"),
                "冷门警觉": str(v2.get("upset_alert_level") or ""),
                "冷门方向": str(v2.get("upset_direction") or ""),
                "冷门防守": str(v2.get("upset_guard_pick") or ""),
                "最终覆盖": final_cover_display,
                "最终Top1": final_top1_display,
                "预测结果": prediction_result_display,
                "子类": str(v2.get("subclass") or ""),
                "偏向": str(v2.get("prediction_bias") or ""),
                "更新时间": _fmt_dt(pred.get("updated_at") or pred.get("created_at") or v2.get("created_at")),
            }
        )
    return pd.DataFrame(data)


def _render_live_match_summary_table(fixtures: List[Dict], preds: Dict[str, Dict], v2_out: Dict[str, Dict]):
    df = _build_live_match_summary_df(fixtures, preds, v2_out)
    if df.empty:
        st.caption("当前比赛日暂无比赛")
        return
    final_missing = max(len(fixtures or []) - len(preds or {}), 0)
    if final_missing:
        st.caption(f"当前比赛日仍有 {final_missing} 场未生成 final 预测，相关列会显示“未生成”或“待解析”。")
    st.dataframe(df, use_container_width=True, hide_index=True)


st.title("📌 v2 执行过程与结果（当日 12:00~次日12:00）")
st.caption("当天定义：当日 12:00 到 次日 12:00 之间的比赛")

now = datetime.now()
today_start, _, today_tag = compute_today_window(now)

with st.sidebar:
    st.success(f"👤 {st.session_state.get('username','')} ({st.session_state.get('role','')})")
    if st.button("⬅️ 返回看板", use_container_width=True):
        st.switch_page("pages/1_Dashboard.py")
    if st.button("退出登录", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.session_state["role"] = ""
        if "auth" in st.query_params:
            del st.query_params["auth"]
        st.switch_page("app.py")

    st.divider()
    selected_day = st.date_input("选择比赛日（按 12:00 归一）", value=today_start.date())
    window_start, window_end, window_tag = _window_from_day(selected_day)
    st.caption(f"window_tag={window_tag}")

    st.divider()
    st.subheader("🛠️ 手动执行")
    v2_bias_mode = st.selectbox("prediction_bias 模式", ["A(保守)", "B(扩展)"])
    limit_snapshots = st.number_input(
        "快照采集 limit（0=不限制）",
        min_value=0,
        max_value=200,
        value=40,
        step=10,
    )
    sleep_s = st.slider("采集间隔（秒）", min_value=0.0, max_value=2.0, value=0.4, step=0.1)

    snapshot_slot = st.selectbox(
        "快照时间点（建议）",
        [
            "手动（当前时间）",
            "T-24（建议 12:10）",
            "T-12（建议 00:00）",
            "T-6（建议 18:00）",
            "T-1（建议 23:00）",
            "close（建议 11:00）",
        ],
    )

    if st.button("🧷 锁定该比赛日赛程", use_container_width=True):
        with st.spinner("正在锁定赛程..."):
            try:
                saved = _lock_window_fixtures(window_start, window_end, window_tag)
                if saved:
                    st.success(f"赛程已锁定 window_tag={window_tag} fixtures={saved}")
                else:
                    st.warning(f"窗口内未抓到比赛 window_tag={window_tag}")
            except Exception as e:
                st.error(f"锁定赛程失败: {e}")
        _load_window_data.clear()
        st.rerun()

    if st.button("📸 采集快照", use_container_width=True):
        with st.spinner("正在采集快照（可能需要几十秒）..."):
            try:
                lim = None if int(limit_snapshots) <= 0 else int(limit_snapshots)
                saved = collect_snapshots_for_window(window_tag, sleep_s=float(sleep_s), limit=lim)
                st.success(f"快照采集完成 {snapshot_slot} window_tag={window_tag} 新增={saved}")
            except Exception as e:
                st.error(f"快照采集失败: {e}")
        _load_window_data.clear()
        st.rerun()

    st.divider()
    st.subheader("🚀 当日批量")
    fixtures_for_actions = _fetch_fixtures_for_window_tag(window_tag)
    if not fixtures_for_actions:
        st.caption("未锁定赛程时无法批量执行")

    if st.button("🧠 当日全部 v2 输出", use_container_width=True, disabled=not fixtures_for_actions):
        with st.spinner("正在批量生成 v2 输出..."):
            os.environ["V2_PREDICTION_BIAS_MODE"] = "B" if v2_bias_mode.startswith("B") else "A"
            db = Database()
            ok = 0
            for fx in fixtures_for_actions:
                fid = str(fx.get("fixture_id") or "")
                if not fid:
                    continue
                try:
                    _run_v2_for_fixture(db, fid, fx, prediction_period="final")
                    ok += 1
                except Exception:
                    continue
            db.close()
            st.success(f"批量 v2 输出完成：{ok}/{len(fixtures_for_actions)}")
        _load_window_data.clear()
        st.rerun()

    if st.button("🤖 当日全部 final 预测", use_container_width=True, disabled=not fixtures_for_actions):
        with st.spinner("正在批量生成 final 预测（耗时较长）..."):
            os.environ["PREDICTION_MARKET_ENGINE_MODE"] = "v2_full"
            db = Database()
            ok = 0
            for fx in fixtures_for_actions:
                fid = str(fx.get("fixture_id") or "")
                if not fid:
                    continue
                try:
                    _run_final_for_fixture(db, fid, fx)
                    ok += 1
                except Exception:
                    continue
            db.close()
            st.success(f"批量 final 预测完成：{ok}/{len(fixtures_for_actions)}")
        _load_window_data.clear()
        st.rerun()

fixtures, snap_stats, preds, v2_out = _load_window_data(window_tag)

if not fixtures:
    st.warning("该比赛日尚未锁定赛程：请先运行 `python scripts/v2_daily_pipeline.py lock`")
    st.info("你也可以在左侧【手动执行】点击：🧷 锁定该比赛日赛程")
    st.stop()

fixture_ids = [str(x.get("fixture_id") or "") for x in fixtures if x.get("fixture_id")]

db = Database()
bucket_cache = {}
for f in fixtures:
    fid = str(f.get("fixture_id") or "")
    kickoff = f.get("kickoff_time")
    if fid:
        try:
            bucket_cache[fid] = _compute_bucket_counts(db, fid, kickoff)
        except Exception:
            bucket_cache[fid] = ({"open": 0, "T-24": 0, "T-12": 0, "T-6": 0, "T-1": 0, "close": 0}, 0, None, None)
db.close()

total = len(fixtures)
has_euro_any = sum(1 for fid in fixture_ids if (snap_stats.get(fid) or {}).get("euro_cnt", 0) > 0)
has_ah_any = sum(1 for fid in fixture_ids if (snap_stats.get(fid) or {}).get("ah_cnt", 0) > 0)
has_pred = sum(1 for fid in fixture_ids if fid in preds)
euro_bucket_ok = sum(1 for fid in fixture_ids if (bucket_cache.get(fid) or ({}, 0, None))[1] >= 3)
missing_snapshot = sum(1 for fid in fixture_ids if (snap_stats.get(fid) or {}).get("euro_cnt", 0) == 0)
missing_pred = sum(1 for fid in fixture_ids if fid not in preds)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("比赛数", total)
col2.metric("欧赔快照覆盖", f"{has_euro_any}/{total}")
col3.metric("亚盘快照覆盖", f"{has_ah_any}/{total}")
col4.metric("欧赔桶>=3", f"{euro_bucket_ok}/{total}")
col5.metric("final 预测", f"{has_pred}/{total}")
col6.metric("缺失提示", f"快照{missing_snapshot} / 预测{missing_pred}")

st.divider()

left, mid = st.columns([1.2, 2.0])
with left:
    st.subheader("📋 当天比赛")
    leagues = sorted(list({str(f.get("league") or "") for f in fixtures if f.get("league")}))
    selected_leagues = st.multiselect("联赛筛选", leagues, default=leagues)
    keyword = st.text_input("关键字（队名/联赛）", value="")
    show_only_missing = st.checkbox("只看缺失（快照或预测）", value=False)

    filtered = []
    for f in fixtures:
        league = str(f.get("league") or "")
        if selected_leagues and league and league not in selected_leagues:
            continue
        text = f"{league} {f.get('home_team','')} {f.get('away_team','')}"
        if keyword and keyword.strip() and keyword.strip() not in text:
            continue
        fid = str(f.get("fixture_id") or "")
        miss = (snap_stats.get(fid) or {}).get("euro_cnt", 0) == 0 or fid not in preds
        if show_only_missing and not miss:
            continue
        filtered.append(f)

    if "v2_selected_fid" not in st.session_state:
        st.session_state["v2_selected_fid"] = ""

    selected_fid = str(st.session_state.get("v2_selected_fid") or "")

    if not filtered:
        st.info("没有匹配的比赛（请调整筛选条件）")
    else:
        if not selected_fid:
            selected_fid = str(filtered[0].get("fixture_id") or "")
            st.session_state["v2_selected_fid"] = selected_fid

        for f in filtered:
            fid = str(f.get("fixture_id") or "")
            kickoff = f.get("kickoff_time")
            s = snap_stats.get(fid) or {}
            counts, present, _, _ = bucket_cache.get(fid) or ({}, 0, None, None)
            miss_euro = s.get("euro_cnt", 0) == 0
            miss_pred = fid not in preds
            flag = "⛔" if miss_pred else "⚠️" if miss_euro or present < 3 else "✅"
            is_selected = fid == selected_fid
            label = f"{flag} {_fmt_dt(kickoff)}  {f.get('league','')}  {f.get('home_team','')} vs {f.get('away_team','')}"
            if is_selected:
                label = f"👉 {label}"
            if st.button(label, key=f"pick_{fid}", use_container_width=True):
                st.session_state["v2_selected_fid"] = fid
                _load_window_data.clear()
                st.rerun()


with mid:
    st.subheader("🧩 单场执行过程")
    if not selected_fid:
        st.info("请先在左侧选择比赛")
    else:
        f = next((x for x in fixtures if str(x.get("fixture_id") or "") == selected_fid), None) or {}
        kickoff = f.get("kickoff_time")
        lock_time = f.get("created_at")
        s = snap_stats.get(selected_fid) or {}
        counts, present, euro_first, euro_last = bucket_cache.get(selected_fid) or ({}, 0, None, None)
        ah_last = s.get("ah_last")
        v2 = v2_out.get(selected_fid) or {}
        p = preds.get(selected_fid) or {}

        st.caption(f"fixture_id={selected_fid}")
        st.write(f"比赛时间：{_fmt_dt(kickoff)}")

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("🧠 单场生成 v2 输出", use_container_width=True):
                with st.spinner("正在生成 v2 引擎输出..."):
                    os.environ["V2_PREDICTION_BIAS_MODE"] = "B" if v2_bias_mode.startswith("B") else "A"
                    db = Database()
                    try:
                        _run_v2_for_fixture(db, selected_fid, f, prediction_period="final")
                        st.success("v2 输出已生成并落库")
                    except Exception as e:
                        st.error(f"生成 v2 输出失败: {e}")
                    db.close()
                _load_window_data.clear()
                st.rerun()
        with b2:
            if st.button("🤖 单场生成 final 预测", use_container_width=True):
                with st.spinner("正在生成 final 预测（可能需要几十秒）..."):
                    db = Database()
                    try:
                        _run_final_for_fixture(db, selected_fid, f)
                        st.success("final 预测已生成并写入数据库")
                    except Exception as e:
                        st.error(f"生成 final 预测失败: {e}")
                    db.close()
                _load_window_data.clear()
                st.rerun()

        _timeline_line("赛程锁定", "ok" if lock_time else "warn", lock_time)
        _timeline_line(
            "欧赔快照",
            "ok" if s.get("euro_cnt", 0) > 0 else "bad",
            euro_last,
            detail=f"{s.get('euro_cnt', 0)} 条，首:{_fmt_dt(euro_first)}",
        )
        _timeline_line(
            "欧赔桶覆盖",
            "ok" if present >= 3 else "warn" if present > 0 else "bad",
            euro_last,
            detail=f"{present}/6 {' '.join([f'{k}:{v}' for k, v in (counts or {}).items()])}",
        )
        _timeline_line(
            "亚盘快照",
            "ok" if s.get("ah_cnt", 0) > 0 else "muted",
            ah_last,
            detail=f"{s.get('ah_cnt', 0)} 条",
        )
        _timeline_line(
            "v2 引擎输出",
            "ok" if v2 else "warn",
            v2.get("created_at") if v2 else None,
            detail=_format_v2_cn(v2) if v2 else "尚无输出",
        )
        _timeline_line(
            "final 预测",
            "ok" if p else "bad",
            (p.get("updated_at") or p.get("created_at")) if p else None,
            detail=(p.get("predicted_result") or "") if p else "缺失",
        )

        st.divider()
        st.subheader("📌 关键数据（单场）")

        db = Database()
        euro_rows = db.fetch_v2_odds_snapshots(selected_fid)
        ah_rows = db.fetch_v2_ah_snapshots(selected_fid)
        db.close()

        euro_bucketed = bucket_by_kickoff(euro_rows, kickoff)
        euro_summary = _build_euro_bucket_summary(euro_bucketed)
        st.write("欧赔快照关键信息")
        st.dataframe(_format_euro_summary_table(euro_summary), use_container_width=True)

        try:
            open_books = [build_euro_book_snapshot(r) for r in euro_bucketed.open]
            close_books = [build_euro_book_snapshot(r) for r in euro_bucketed.close]
            open_books = [b for b in open_books if b is not None]
            close_books = [b for b in close_books if b is not None]
            if open_books and close_books:
                open_cons = consensus_from_books(open_books)
                close_cons = consensus_from_books(close_books)
                shift = dominant_shift(open_cons, close_cons)
                if shift is not None:
                    side, delta, _ = shift
                    st.caption(f"dominant_shift: {side} {delta:+.4f}")
        except Exception:
            pass

        st.write("亚盘快照关键信息（macau/bet365）")
        ah_summ = _summarize_ah_rows(ah_rows)
        if ah_summ:
            st.dataframe(
                [
                    {
                        "公司": x["book"],
                        "首个": _fmt_dt(x["first_time"]),
                        "首盘口": x["first_line"],
                        "首主水": x["first_home"],
                        "首客水": x["first_away"],
                        "最新": _fmt_dt(x["last_time"]),
                        "最新盘口": x["last_line"],
                        "最新主水": x["last_home"],
                        "最新客水": x["last_away"],
                    }
                    for x in ah_summ
                ],
                use_container_width=True,
            )
        else:
            st.caption("暂无可用亚盘快照")

        st.write("v2 引擎输出")
        if v2:
            st.write(_format_v2_cn(v2))
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("程序主推", v2.get("nspf_top1") or "-")
            d2.metric("程序覆盖", v2.get("nspf_cover") or "-")
            d3.metric("程序置信度", v2.get("nspf_confidence") or "-")
            d4.metric("冷门警觉", v2.get("upset_alert_level") or "-")
            if v2.get("why"):
                st.text_area("why", v2.get("why") or "", height=120, disabled=True)
            if v2.get("decision_reason"):
                st.text_area("decision_reason", v2.get("decision_reason") or "", height=110, disabled=True)
            if v2.get("upset_reasons"):
                st.text_area("upset_reasons", " / ".join(v2.get("upset_reasons") or []), height=80, disabled=True)
        else:
            st.caption("尚无 v2 引擎输出")

        st.write("final 预测")
        if p and p.get("prediction_text"):
            st.text_area("预测全文", p.get("prediction_text") or "", height=260, disabled=True)
        elif p:
            st.caption("预测已入库但正文为空")
        else:
            st.caption("缺失 final 预测")


with st.expander("比赛汇总展示（当天预测执行情况）", expanded=True):
    st.caption("这里展示当前比赛日的赛程和已执行预测情况，不依赖赛果，也不依赖日报是否已生成。支持收缩查看。")
    _render_live_match_summary_table(fixtures, preds, v2_out)

st.divider()
st.subheader("🧾 v2 每日复盘执行过程")

db = Database()
try:
    available_report_dates = db.list_v2_daily_report_dates(limit=120) or []
finally:
    db.close()

default_target = window_start.strftime("%Y-%m-%d")
report_date_options = list(dict.fromkeys([default_target] + available_report_dates))
default_report_index = report_date_options.index(default_target) if default_target in report_date_options else 0

selected_report_date = st.selectbox(
    "🎯 目标复盘日期 (生成日报、查看均针对此日期)",
    options=report_date_options,
    index=default_report_index,
    key="v2_report_selected_date",
)

st.write("反馈调权参数配置")
r_col1, r_col2, r_col3, r_col4, r_col5 = st.columns(5)
with r_col1:
    review_since = st.date_input("反馈开始", value=window_start.date() - timedelta(days=13), key="v2_review_since")
with r_col2:
    review_until = st.date_input("反馈结束", value=window_start.date(), key="v2_review_until")
with r_col3:
    min_samples = st.number_input("最小样本", min_value=5, max_value=200, value=20, step=5, key="v2_review_min_samples")
with r_col4:
    step_value = st.slider("步长", min_value=0.005, max_value=0.03, value=0.01, step=0.005, key="v2_review_step")
with r_col5:
    margin_value = st.slider("阈值", min_value=0.01, max_value=0.08, value=0.03, step=0.01, key="v2_review_margin")

act1, act2, act3, act4, act5 = st.columns(5)
if act1.button("📥 更新赛果", use_container_width=True):
    with st.spinner(f"正在抓取 {selected_report_date} 赛果..."):
        try:
            updated, total = update_results_for_target_date(selected_report_date)
            st.session_state["v2_postmortem_result"] = {
                "target_date": selected_report_date,
                "updated": updated,
                "total": total,
            }
            st.success(f"赛果更新完成（{selected_report_date}）：{updated}/{total}")
        except Exception as e:
            st.error(f"更新赛果失败: {e}")
            st.stop()
    _load_window_data.clear()
    st.rerun()

if act2.button("📝 生成 v2 日报", use_container_width=True):
    with st.spinner(f"正在生成 {selected_report_date} v2 日报..."):
        try:
            report_path = generate_daily_report(selected_report_date)
            db = Database()
            try:
                persisted_rows = len(db.get_v2_daily_report_rows(selected_report_date))
            finally:
                db.close()
            st.session_state["v2_daily_report_path"] = report_path
            st.success(f"日报已生成（{selected_report_date}）：{report_path or '无'}，明细落库 {persisted_rows} 条")
        except Exception as e:
            st.error(f"生成日报失败: {e}")
            st.stop()
    _load_window_data.clear()
    st.rerun()

if act3.button("🧪 预演调权", use_container_width=True):
    with st.spinner("正在预演反馈优化..."):
        try:
            result = optimize_feedback(
                since=review_since,
                until=review_until,
                min_samples=int(min_samples),
                step=float(step_value),
                margin=float(margin_value),
                dry_run=True,
            )
            st.session_state["v2_feedback_dry_run"] = result
            st.success(f"预演完成：样本 {result.get('rows', 0)}，建议变更 {len(result.get('updates', []))} 项")
        except Exception as e:
            st.error(f"预演调权失败: {e}")

if act4.button("✅ 应用调权", use_container_width=True):
    with st.spinner("正在应用反馈优化..."):
        try:
            result = optimize_feedback(
                since=review_since,
                until=review_until,
                min_samples=int(min_samples),
                step=float(step_value),
                margin=float(margin_value),
                dry_run=False,
            )
            st.session_state["v2_feedback_apply"] = result
            st.success(f"调权已应用：样本 {result.get('rows', 0)}，实际变更 {len(result.get('updates', []))} 项")
        except Exception as e:
            st.error(f"应用调权失败: {e}")

if act5.button("📦 一键流程", use_container_width=True):
    with st.spinner(f"正在执行（{selected_report_date}）：更新赛果 -> 生成日报 -> 预演调权..."):
        try:
            updated, total = update_results_for_target_date(selected_report_date)
            report_path = generate_daily_report(selected_report_date)
            db = Database()
            try:
                persisted_rows = len(db.get_v2_daily_report_rows(selected_report_date))
            finally:
                db.close()
            dry_run_result = optimize_feedback(
                since=review_since,
                until=review_until,
                min_samples=int(min_samples),
                step=float(step_value),
                margin=float(margin_value),
                dry_run=True,
            )
            st.session_state["v2_postmortem_result"] = {
                "target_date": selected_report_date,
                "updated": updated,
                "total": total,
            }
            st.session_state["v2_daily_report_path"] = report_path
            st.session_state["v2_feedback_dry_run"] = dry_run_result
            st.success(
                f"流程完成（{selected_report_date}）：赛果 {updated}/{total}，明细落库 {persisted_rows} 条，预演建议 {len(dry_run_result.get('updates', []))} 项"
            )
        except Exception as e:
            st.error(f"一键流程执行失败: {e}")
            st.stop()
    _load_window_data.clear()
    st.rerun()

last_postmortem = st.session_state.get("v2_postmortem_result") or {}
last_report_path = str(st.session_state.get("v2_daily_report_path") or "")
last_dry_run = st.session_state.get("v2_feedback_dry_run") or {}
last_apply = st.session_state.get("v2_feedback_apply") or {}

db = Database()
try:
    selected_persisted_report = db.get_v2_daily_report(selected_report_date) or {}
    selected_persisted_report_rows = db.get_v2_daily_report_rows(selected_report_date) or []
finally:
    db.close()

selected_report_path = str(selected_persisted_report.get("report_path") or "")
selected_markdown = str(selected_persisted_report.get("markdown_content") or "")
effective_report_path = last_report_path if selected_report_date == last_postmortem.get("target_date") and last_report_path else selected_report_path
effective_report_text = selected_markdown or (_safe_read_text(effective_report_path) if effective_report_path else "")

proc1, proc2, proc3, proc4 = st.columns(4)
proc1.metric("赛果更新", f"{last_postmortem.get('updated', 0)}/{last_postmortem.get('total', 0)}")
proc2.metric("日报状态", "已落库" if selected_persisted_report else ("已生成" if effective_report_path else "未生成"))
proc3.metric("预演建议", len(last_dry_run.get("updates", []) or []))
proc4.metric("日报明细数", len(selected_persisted_report_rows or []))

with st.expander(f"查看 {selected_report_date} 的日报与调权结果", expanded=False):
    if last_postmortem and last_postmortem.get("target_date") == selected_report_date:
        st.write(
            f"- 最近赛果更新：{last_postmortem.get('target_date', '-')}"
            f" / {last_postmortem.get('updated', 0)}/{last_postmortem.get('total', 0)}"
        )
    if selected_persisted_report:
        st.write(f"- 持久化日期：`{selected_persisted_report.get('target_date')}`")
        st.write(f"- 最近更新时间：`{selected_persisted_report.get('updated_at')}`")
    if effective_report_path:
        st.write(f"- 日报路径：`{effective_report_path}`")
        if effective_report_text:
            st.write("日报单场复盘明细")
            _render_match_summary_table(selected_persisted_report_rows)
            st.write("日报汇总预览")
            _render_v2_daily_report_preview(effective_report_text)
    else:
        st.caption(f"尚未生成 {selected_report_date} 的 v2 日报")

    if last_dry_run:
        st.write("预演调权结果")
        st.json(last_dry_run)
    if last_apply:
        st.write("已应用调权结果")
        st.json(last_apply)
    if not last_dry_run and not last_apply:
        st.caption("尚无反馈优化结果")

st.info(
    "推荐流程：1) 先更新赛果  2) 生成 v2 日报  3) 预演反馈调权  4) 确认无误后应用调权。"
)

st.divider()
st.subheader("✅ 快照与预测状态汇总")

missing_snap_fids = [fid for fid in fixture_ids if (snap_stats.get(fid) or {}).get("euro_cnt", 0) == 0]
missing_pred_fids = [fid for fid in fixture_ids if fid not in preds]
low_bucket_fids = [fid for fid in fixture_ids if (bucket_cache.get(fid) or ({}, 0, None, None))[1] < 3]

g1, g2, g3 = st.columns(3)
with g1:
    st.write("快照缺失（欧赔）")
    if missing_snap_fids:
        _badge(f"{len(missing_snap_fids)} 场", "bad")
        st.code("\n".join(missing_snap_fids[:50]))
    else:
        _badge("0 场", "ok")

with g2:
    st.write("桶数不足（欧赔桶<3）")
    if low_bucket_fids:
        _badge(f"{len(low_bucket_fids)} 场", "warn")
        st.code("\n".join(low_bucket_fids[:50]))
    else:
        _badge("0 场", "ok")

with g3:
    st.write("final 预测缺失")
    if missing_pred_fids:
        _badge(f"{len(missing_pred_fids)} 场", "warn")
        st.code("\n".join(missing_pred_fids[:50]))
    else:
        _badge("0 场", "ok")

st.write("操作建议")
st.write("- 若未锁定赛程：在左侧点击 🧷 锁定该比赛日赛程（或运行 `python scripts/v2_daily_pipeline.py lock`）")
st.write("- 若快照不足：在多个固定时间点点击 📸 采集快照（或运行 `python scripts/v2_daily_pipeline.py snapshot`）")
st.write("- 若缺失 final：运行 `python scripts/v2_daily_pipeline.py final`")
