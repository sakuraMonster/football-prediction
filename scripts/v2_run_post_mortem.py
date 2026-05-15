import os
import sys
import datetime
import json

from sqlalchemy import text

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.db.database import Database


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _now_text():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def compute_v2_market_report(target_date=None):
    if target_date is None:
        target_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    window_start = f"{target_date} 12:00:00"
    next_day = (datetime.datetime.strptime(target_date, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    window_end = f"{next_day} 12:00:00"
    batch_label = f"{target_date} 12:00 ~ {next_day} 12:00"

    db = Database()

    pred_query = text(
        """
        SELECT m1.*
        FROM match_predictions m1
        JOIN (
            SELECT match_num, DATE(match_time) as m_date,
                   COALESCE(
                     MAX(CASE WHEN prediction_period = 'repredicted' THEN id END),
                     MAX(CASE WHEN prediction_period NOT IN ('historical', 'repredicted') THEN id END),
                     MAX(id)
                   ) as max_id
            FROM match_predictions
            WHERE match_time >= :window_start AND match_time < :window_end
              AND prediction_period != 'historical'
            GROUP BY match_num, DATE(match_time)
        ) m2 ON m1.id = m2.max_id
        WHERE m1.actual_score IS NOT NULL AND m1.actual_score != '' AND m1.actual_score != '暂无'
          AND m1.prediction_text IS NOT NULL AND m1.prediction_text != ''
        ORDER BY m1.match_time
        """
    )
    preds = db.session.execute(pred_query, {"window_start": window_start, "window_end": window_end}).fetchall()

    meta = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='v2_script_output'")
    )
    has_v2_table = meta.fetchone() is not None

    report = {
        "date": target_date,
        "batch_label": batch_label,
        "generated_at": _now_text(),
        "overall": {
            "total": 0,
            "with_v2": 0,
            "action_type_counts": {},
            "strength_counts": {},
            "prototype_counts": {},
            "subclass_counts": {},
            "monitor_status": {},
        },
        "samples": [],
    }

    if not preds or not has_v2_table:
        db.close()
        return report

    for row in preds:
        report["overall"]["total"] += 1
        mapping = getattr(row, "_mapping", None) or {}
        fixture_id = (mapping.get("fixture_id") or "")
        period = (mapping.get("prediction_period") or "final")
        league = (mapping.get("league") or "")
        match_num = (mapping.get("match_num") or "")
        home = (mapping.get("home_team") or "")
        away = (mapping.get("away_team") or "")
        actual_score = (mapping.get("actual_score") or "")

        v2 = db.session.execute(
            text(
                """
                SELECT prototype, subclass, action_type, strength, direction_hint, why, mode, engine_version, created_at,
                       signal_bucket, clv_prob, clv_logit, dispersion
                FROM v2_script_output
                WHERE fixture_id = :fixture_id AND prediction_period = :period
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"fixture_id": fixture_id, "period": period},
        ).fetchone()

        if not v2:
            continue

        report["overall"]["with_v2"] += 1
        (
            prototype,
            subclass,
            action_type,
            strength,
            direction_hint,
            why,
            mode,
            engine_version,
            created_at,
            signal_bucket,
            clv_prob,
            clv_logit,
            dispersion,
        ) = v2

        def _inc(d, k):
            d[k] = _safe_int(d.get(k), 0) + 1

        _inc(report["overall"]["action_type_counts"], str(action_type or ""))
        _inc(report["overall"]["strength_counts"], str(strength or ""))
        _inc(report["overall"]["prototype_counts"], str(prototype or ""))
        _inc(report["overall"]["subclass_counts"], str(subclass or ""))

        clv_bucket = report["overall"].setdefault("clv", {"n": 0, "rate": None, "magnitude": None})
        if clv_prob is not None:
            clv_bucket["n"] = _safe_int(clv_bucket.get("n"), 0) + 1
            clv_bucket.setdefault("_sum", 0.0)
            clv_bucket.setdefault("_pos", 0)
            clv_bucket["_sum"] += float(clv_prob)
            if float(clv_prob) > 0:
                clv_bucket["_pos"] += 1

        if len(report["samples"]) < 40:
            report["samples"].append(
                {
                    "match_num": match_num,
                    "league": league,
                    "home": home,
                    "away": away,
                    "actual_score": actual_score,
                    "prediction_period": period,
                    "v2": {
                        "prototype": prototype,
                        "subclass": subclass,
                        "action_type": action_type,
                        "strength": strength,
                        "direction_hint": direction_hint,
                        "why": why,
                        "mode": mode,
                        "engine_version": engine_version,
                        "created_at": str(created_at or ""),
                        "signal_bucket": signal_bucket,
                        "clv_prob": clv_prob,
                        "clv_logit": clv_logit,
                        "dispersion": dispersion,
                    },
                }
            )

    db.close()

    try:
        db = Database()
        meta = db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='v2_monitor_metrics'")
        )
        has_monitor = meta.fetchone() is not None
        if has_monitor:
            rows = db.session.execute(
                text(
                    """
                    SELECT subclass, league, status, ewma_clv, clv_rate, clv_magnitude, n
                    FROM v2_monitor_metrics
                    WHERE window_name = 'mid'
                    ORDER BY updated_at DESC
                    """
                )
            ).fetchall()
            seen = set()
            for r in rows:
                key = f"{r[0]}|{r[1]}"
                if key in seen:
                    continue
                seen.add(key)
                report["overall"]["monitor_status"][key] = {
                    "status": r[2],
                    "ewma_clv": r[3],
                    "clv_rate": r[4],
                    "clv_magnitude": r[5],
                    "n": r[6],
                }
        db.close()
    except Exception:
        pass

    clv = report.get("overall", {}).get("clv") or {}
    if clv.get("n"):
        n = int(clv["n"])
        s = float(clv.get("_sum") or 0.0)
        p = int(clv.get("_pos") or 0)
        clv["rate"] = p / n
        clv["magnitude"] = s / n
    for key in ["_sum", "_pos"]:
        if key in clv:
            del clv[key]
    return report


def write_v2_reports(target_date=None):
    report = compute_v2_market_report(target_date)

    reports_dir = os.path.join(project_root, "data", "reports")
    os.makedirs(reports_dir, exist_ok=True)

    date = report.get("date") or "unknown"
    json_path = os.path.join(reports_dir, f"v2_market_post_mortem_{date}.json")
    md_path = os.path.join(reports_dir, f"v2_market_post_mortem_{date}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    overall = report.get("overall") or {}
    lines = [
        f"# v2 市场剧本复盘（{report.get('batch_label','')}）",
        "",
        f"- 生成时间：{report.get('generated_at','')}",
        f"- 总场次：{overall.get('total',0)}",
        f"- 具备 v2 输出的场次：{overall.get('with_v2',0)}",
        f"- CLV：{overall.get('clv',{})}",
        "",
        "## 统计",
        "",
        f"- action_type_counts：{overall.get('action_type_counts',{})}",
        f"- strength_counts：{overall.get('strength_counts',{})}",
        "",
        "## prototype_counts",
        "",
        "```json",
        json.dumps(overall.get("prototype_counts", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## subclass_counts",
        "",
        "```json",
        json.dumps(overall.get("subclass_counts", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## monitor_status（mid window）",
        "",
        "```json",
        json.dumps(overall.get("monitor_status", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 样例（最多 40 场）",
        "",
        "```json",
        json.dumps(report.get("samples", []), ensure_ascii=False, indent=2),
        "```",
        "",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    jp, mp = write_v2_reports(date_arg)
    print(f"✅ v2 复盘已输出: {jp}")
    print(f"✅ v2 复盘已输出: {mp}")
