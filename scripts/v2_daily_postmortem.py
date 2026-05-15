import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.db.database import Database
from src.market_script_v2.daily_window import compute_today_window
from src.market_script_v2.features.euro import build_euro_book_snapshot, consensus_from_books
from src.market_script_v2.features.time_buckets import bucket_by_kickoff
from src.utils.nspf_summary import build_pick_summary, extract_nspf_tokens, extract_report_nspf_cover


def _tokens_from_text(text: str) -> List[str]:
    return extract_nspf_tokens(text)


def _baseline_pick_from_snapshots(euro_rows: List[Dict], kickoff: Optional[datetime]):
    if not euro_rows:
        return ""
    bucketed = bucket_by_kickoff(euro_rows, kickoff)
    close_rows = bucketed.close or []
    if not close_rows:
        close_rows = euro_rows
    books = [build_euro_book_snapshot(r) for r in close_rows]
    books = [b for b in books if b is not None]
    if not books:
        return ""
    cons = consensus_from_books(books)
    probs = [("胜", cons.p_home), ("平", cons.p_draw), ("负", cons.p_away)]
    probs = [(k, v) for k, v in probs if v is not None]
    if not probs:
        return ""
    probs.sort(key=lambda x: x[1], reverse=True)
    return probs[0][0]


def _safe_pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "0.0%"
    return f"{(numerator / denominator):.1%}"


def _group_summary(rows: List[Dict], key: str, *, top_n: int = 12) -> List[Dict]:
    grouped: Dict[str, Dict[str, int]] = {}
    for row in rows:
        label = str(row.get(key) or "未分类")
        stat = grouped.setdefault(
            label,
            {
                "n": 0,
                "prog_top1_hit": 0,
                "prog_cover_hit": 0,
                "final_top1_hit": 0,
                "final_cover_hit": 0,
                "baseline_hit": 0,
            },
        )
        stat["n"] += 1
        stat["prog_top1_hit"] += int(row.get("prog_top1_hit") or 0)
        stat["prog_cover_hit"] += int(row.get("prog_cover_hit") or 0)
        stat["final_top1_hit"] += int(row.get("final_top1_hit") or 0)
        stat["final_cover_hit"] += int(row.get("final_cover_hit") or 0)
        stat["baseline_hit"] += int(row.get("baseline_hit") or 0)

    summary = []
    for label, stat in grouped.items():
        n = stat["n"]
        summary.append(
            {
                "label": label,
                "n": n,
                "prog_top1_acc": stat["prog_top1_hit"] / n if n else 0,
                "prog_cover_acc": stat["prog_cover_hit"] / n if n else 0,
                "final_top1_acc": stat["final_top1_hit"] / n if n else 0,
                "final_cover_acc": stat["final_cover_hit"] / n if n else 0,
                "baseline_acc": stat["baseline_hit"] / n if n else 0,
            }
        )
    summary.sort(key=lambda item: (item["n"], item["prog_cover_acc"], item["prog_top1_acc"]), reverse=True)
    return summary[:top_n]


def build_daily_report_payload(target_date: str) -> Dict[str, object]:
    db = Database()
    preds = db.get_predictions_by_date(target_date)
    if not preds:
        db.close()
        return {}

    fixture_ids = [str(getattr(r, "fixture_id", "") or "") for r in preds if getattr(r, "fixture_id", None)]
    v2_outputs = db.fetch_latest_v2_script_output_for_fixtures(fixture_ids, prediction_period="final")

    rows = []
    for r in preds:
        fid = r.fixture_id
        kickoff = r.match_time
        actual = r.actual_result or ""
        pred_text = r.prediction_text or ""

        v2_output = v2_outputs.get(str(fid)) or {}
        prog_summary = build_pick_summary(
            cover_text=str(v2_output.get("nspf_cover") or v2_output.get("nspf_top1") or ""),
            scores=v2_output.get("nspf_scores"),
            primary_token=str(v2_output.get("nspf_top1") or ""),
        )
        prog_cover = str(prog_summary.get("cover") or "")
        prog_top1_display = str(prog_summary.get("display") or "")
        prog_primary = str(prog_summary.get("primary") or "")
        prog_tokens = _tokens_from_text(prog_cover)
        prog_cover_hit = 1 if (actual and actual in prog_tokens) else 0
        prog_top1_hit = 1 if (actual and prog_primary and actual == prog_primary) else 0

        final_cover = extract_report_nspf_cover(pred_text, r.predicted_result or "")
        final_summary = build_pick_summary(
            cover_text=final_cover,
            scores=v2_output.get("nspf_scores"),
            primary_token=prog_primary,
        )
        final_cover = str(final_summary.get("cover") or "")
        final_top1_display = str(final_summary.get("display") or "")
        final_primary = str(final_summary.get("primary") or "")
        final_tokens = _tokens_from_text(final_cover)
        final_cover_hit = 1 if (actual and actual in final_tokens) else 0
        final_top1_hit = 1 if (actual and final_primary and actual == final_primary) else 0

        euro_rows = db.fetch_v2_odds_snapshots(str(fid))
        baseline = _baseline_pick_from_snapshots(euro_rows, kickoff)
        baseline_hit = 1 if (actual and baseline and actual == baseline) else 0

        league = r.league or v2_output.get("league") or ""
        subclass = str(v2_output.get("subclass") or "")
        prediction_bias = str(v2_output.get("prediction_bias") or "")
        prototype = str(v2_output.get("prototype") or "")
        feedback_tag = str(v2_output.get("feedback_tag") or "")
        prog_conf = v2_output.get("nspf_confidence")
        league_subclass = f"{league}/{subclass}" if league and subclass else subclass or league or "未分类"

        rows.append(
            {
                "fixture_id": fid,
                "match_num": r.match_num,
                "league": league,
                "home": r.home_team,
                "away": r.away_team,
                "kickoff": kickoff.isoformat(sep=" ") if isinstance(kickoff, datetime) else str(kickoff or ""),
                "actual": actual,
                "final_cover": final_cover,
                "final_top1": final_top1_display,
                "final_cover_hit": final_cover_hit,
                "final_top1_hit": final_top1_hit,
                "prog_cover": prog_cover or "".join(prog_tokens),
                "prog_top1": prog_top1_display,
                "prog_cover_hit": prog_cover_hit,
                "prog_top1_hit": prog_top1_hit,
                "baseline": baseline,
                "baseline_hit": baseline_hit,
                "subclass": subclass,
                "prototype": prototype,
                "prediction_bias": prediction_bias,
                "feedback_tag": feedback_tag,
                "prog_confidence": prog_conf,
                "league_subclass": league_subclass,
            }
        )

    n = len(rows)
    payload = {
        "target_date": target_date,
        "window_start": datetime.strptime(target_date, "%Y-%m-%d"),
        "window_end": datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1),
        "rows": rows,
        "metrics": {
            "场次": n,
            "程序化覆盖命中率": sum(x["prog_cover_hit"] for x in rows) / n if n else 0,
            "程序化Top1命中率": sum(x["prog_top1_hit"] for x in rows) / n if n else 0,
            "最终文本覆盖命中率": sum(x["final_cover_hit"] for x in rows) / n if n else 0,
            "最终文本Top1命中率": sum(x["final_top1_hit"] for x in rows) / n if n else 0,
            "欧赔close基准命中率": sum(x["baseline_hit"] for x in rows) / n if n else 0,
        },
        "subclass_summary": _group_summary(rows, "subclass", top_n=12),
        "bias_summary": _group_summary(rows, "prediction_bias", top_n=12),
        "league_subclass_summary": _group_summary(rows, "league_subclass", top_n=12),
    }
    db.close()
    return payload


def render_daily_report_markdown(payload: Dict[str, object]) -> str:
    if not payload:
        return ""

    target_date = str(payload.get("target_date") or "")
    rows = payload.get("rows") or []
    metrics = payload.get("metrics") or {}
    subclass_summary = payload.get("subclass_summary") or []
    bias_summary = payload.get("bias_summary") or []
    league_subclass_summary = payload.get("league_subclass_summary") or []

    lines = []
    lines.append(f"# v2 当日复盘 {target_date}（12:00~次日12:00）\n")
    lines.append(f"- 场次：{int(metrics.get('场次') or 0)}")
    lines.append(f"- 程序化覆盖命中率：{float(metrics.get('程序化覆盖命中率') or 0):.1%}")
    lines.append(f"- 程序化Top1命中率：{float(metrics.get('程序化Top1命中率') or 0):.1%}")
    lines.append(f"- 最终文本覆盖命中率：{float(metrics.get('最终文本覆盖命中率') or 0):.1%}")
    lines.append(f"- 最终文本Top1命中率：{float(metrics.get('最终文本Top1命中率') or 0):.1%}")
    lines.append(f"- 欧赔close基准命中率：{float(metrics.get('欧赔close基准命中率') or 0):.1%}\n")

    lines.append("## 单场明细")
    lines.append("| 场次 | 联赛 | 对阵 | 实际 | 程序覆盖 | 程序Top1 | 最终覆盖 | 最终Top1 | 基准 | 子类 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for x in rows:
        matchup = f"{x['home']} vs {x['away']}"
        lines.append(
            f"| {x['match_num']} | {x['league']} | {matchup} | {x['actual']} | {x['prog_cover']} | {x['prog_top1']} | {x['final_cover']} | {x['final_top1']} | {x['baseline']} | {x['subclass']} |"
        )

    if subclass_summary:
        lines.append("\n## 子类表现")
        lines.append("| 子类 | 样本 | 程序Top1 | 程序覆盖 | 最终Top1 | 最终覆盖 | 基准 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in subclass_summary:
            lines.append(
                f"| {item['label']} | {item['n']} | {item['prog_top1_acc']:.1%} | {item['prog_cover_acc']:.1%} | {item['final_top1_acc']:.1%} | {item['final_cover_acc']:.1%} | {item['baseline_acc']:.1%} |"
            )

    if bias_summary:
        lines.append("\n## 偏向表现")
        lines.append("| 偏向 | 样本 | 程序Top1 | 程序覆盖 | 最终Top1 | 最终覆盖 | 基准 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in bias_summary:
            lines.append(
                f"| {item['label']} | {item['n']} | {item['prog_top1_acc']:.1%} | {item['prog_cover_acc']:.1%} | {item['final_top1_acc']:.1%} | {item['final_cover_acc']:.1%} | {item['baseline_acc']:.1%} |"
            )

    if league_subclass_summary:
        lines.append("\n## 联赛子类表现")
        lines.append("| 联赛/子类 | 样本 | 程序Top1 | 程序覆盖 | 最终Top1 | 最终覆盖 | 基准 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in league_subclass_summary:
            lines.append(
                f"| {item['label']} | {item['n']} | {item['prog_top1_acc']:.1%} | {item['prog_cover_acc']:.1%} | {item['final_top1_acc']:.1%} | {item['final_cover_acc']:.1%} | {item['baseline_acc']:.1%} |"
            )

    return "\n".join(lines) + "\n"


def update_results_for_target_date(target_date: str) -> Tuple[int, int]:
    db = Database()
    preds = db.get_predictions_by_date(target_date)
    if not preds:
        db.close()
        return 0, 0

    crawler = JingcaiCrawler()
    window_start = datetime.strptime(target_date, "%Y-%m-%d")
    day0 = window_start.strftime("%Y-%m-%d")
    day1 = (window_start + timedelta(days=1)).strftime("%Y-%m-%d")

    results: Dict[str, Dict] = {}
    for date_str in [day0, day1]:
        daily = crawler.fetch_match_results(target_date=date_str)
        for k, v in (daily or {}).items():
            results[str(k)] = v

    updated = 0
    total = 0
    for r in preds:
        total += 1
        if r.actual_score:
            continue
        match_num = getattr(r, "match_num", "") or ""
        res = results.get(str(match_num))
        if not res:
            continue
        score = res.get("score")
        bqc = res.get("bqc_result")
        if score:
            if db.update_actual_result(r.fixture_id, score, bqc_result=bqc):
                updated += 1

    db.close()
    return updated, total


def generate_daily_report(target_date: str, out_dir: str = os.path.join("data", "reports")) -> str:
    payload = build_daily_report_payload(target_date)
    if not payload:
        return ""
    markdown_content = render_daily_report_markdown(payload)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"v2_daily_eval_{target_date}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    db = Database()
    try:
        metrics = payload.get("metrics") or {}
        ok = db.save_v2_daily_report(
            target_date=target_date,
            report_path=out_path,
            window_start=payload.get("window_start"),
            window_end=payload.get("window_end"),
            total_matches=int(metrics.get("场次") or 0),
            prog_cover_acc=metrics.get("程序化覆盖命中率"),
            prog_top1_acc=metrics.get("程序化Top1命中率"),
            final_cover_acc=metrics.get("最终文本覆盖命中率"),
            final_top1_acc=metrics.get("最终文本Top1命中率"),
            baseline_acc=metrics.get("欧赔close基准命中率"),
            metrics_json=metrics,
            markdown_content=markdown_content,
            rows=payload.get("rows") or [],
        )
        if not ok:
            raise RuntimeError("v2 日报写入数据库失败")
        expected_rows = len(payload.get("rows") or [])
        actual_rows = len(db.get_v2_daily_report_rows(target_date))
        if expected_rows != actual_rows:
            raise RuntimeError(f"v2 日报明细写库数量不一致，期望 {expected_rows}，实际 {actual_rows}")
    finally:
        db.close()
    return out_path


def run_daily_postmortem(now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or datetime.now()
    window_start, _, _ = compute_today_window(now)
    target_date = window_start.strftime("%Y-%m-%d")
    updated, total = update_results_for_target_date(target_date)
    report_path = generate_daily_report(target_date)
    return {"target_date": target_date, "updated": updated, "total": total, "report": report_path}


if __name__ == "__main__":
    res = run_daily_postmortem()
    print(res)
