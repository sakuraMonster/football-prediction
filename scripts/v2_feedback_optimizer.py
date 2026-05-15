import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Union

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.db.database import Database


CONFIG_PATH = os.path.join(project_root, "data", "rules", "v2_decision_weights.json")


def _normalize_ymd(value: Union[str, date, datetime]) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    if not text:
        raise ValueError("日期不能为空，格式应为 YYYY-MM-DD")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"无法识别日期：{text}，请使用 YYYY-MM-DD")


def _daterange(since: str, until: str) -> List[str]:
    start = datetime.strptime(_normalize_ymd(since), "%Y-%m-%d")
    end = datetime.strptime(_normalize_ymd(until), "%Y-%m-%d")
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days


def _tokens(text: str) -> List[str]:
    text = str(text or "")
    return [token for token in ["胜", "平", "负"] if token in text]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _load_config() -> Dict:
    if not os.path.exists(CONFIG_PATH):
        return {"version": 1, "defaults": {"subclass": {}}, "overrides": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: Dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _bias_type_from_row(row: Dict) -> str:
    prediction_bias = str(row.get("prediction_bias") or "")
    tokens = _tokens(prediction_bias)
    if not tokens:
        tokens = _tokens(str(row.get("prog_cover") or row.get("prog_top1") or ""))
    if len(tokens) >= 2:
        return "double"
    if len(tokens) == 1:
        return "single"
    return "unknown"


def _normalize_feedback_row(row: Dict, *, target_date: str, source: str) -> Optional[Dict]:
    actual = str(row.get("actual") or row.get("actual_result") or "").strip()
    if actual not in {"胜", "平", "负"}:
        return None
    subclass = str(row.get("subclass") or "").strip().lower()
    out = {
        "target_date": str(target_date),
        "source": source,
        "fixture_id": str(row.get("fixture_id") or ""),
        "league": str(row.get("league") or ""),
        "subclass": subclass,
        "prediction_bias": str(row.get("prediction_bias") or ""),
        "league_subclass": str(row.get("league_subclass") or ""),
        "actual": actual,
        "prog_top1_hit": int(bool(row.get("prog_top1_hit"))),
        "prog_cover_hit": int(bool(row.get("prog_cover_hit"))),
        "reference_hit": int(bool(row.get("reference_hit") if row.get("reference_hit") is not None else row.get("final_cover_hit"))),
        "bias_type": _bias_type_from_row(row),
    }
    return out


def _collect_rows_from_reports(db: Database, since: str, until: str) -> List[Dict]:
    rows: List[Dict] = []
    for target_date in _daterange(since, until):
        daily_rows = db.get_v2_daily_report_rows(target_date)
        for item in daily_rows or []:
            normalized = _normalize_feedback_row(item, target_date=target_date, source="v2_daily_report_rows")
            if normalized:
                rows.append(normalized)
    return rows


def _collect_rows_legacy(db: Database, since: str, until: str) -> List[Dict]:
    rows: List[Dict] = []
    for target_date in _daterange(since, until):
        daily_rows = db.get_v2_daily_report_rows(target_date)
        if daily_rows:
            continue
        preds = db.get_predictions_by_date(target_date)
        if not preds:
            continue
        fixture_ids = [str(getattr(r, "fixture_id", "") or "") for r in preds if getattr(r, "fixture_id", None)]
        v2_outputs = db.fetch_latest_v2_script_output_for_fixtures(fixture_ids, prediction_period="final")
        for pred in preds:
            actual = str(getattr(pred, "actual_result", "") or "")
            if actual not in {"胜", "平", "负"}:
                continue
            fid = str(getattr(pred, "fixture_id", "") or "")
            v2 = v2_outputs.get(fid) or {}
            if not v2:
                continue
            cover = str(v2.get("nspf_cover") or "")
            top1 = str(v2.get("nspf_top1") or "")
            cover_tokens = _tokens(cover or top1)
            normalized = _normalize_feedback_row(
                {
                    "fixture_id": fid,
                    "league": str(getattr(pred, "league", "") or v2.get("league") or ""),
                    "subclass": str(v2.get("subclass") or ""),
                    "prediction_bias": str(v2.get("prediction_bias") or ""),
                    "actual": actual,
                    "prog_top1_hit": int(bool(top1 and top1 == actual)),
                    "prog_cover_hit": int(bool(actual in cover_tokens)),
                    "reference_hit": int(
                        bool(
                            str(getattr(pred, "predicted_result", "") or "")
                            and actual in _tokens(str(getattr(pred, "predicted_result", "") or ""))
                        )
                    ),
                    "prog_cover": cover,
                    "prog_top1": top1,
                },
                target_date=target_date,
                source="legacy_predictions",
            )
            if normalized:
                rows.append(normalized)
    return rows


def _collect_coverage(db: Database, since: str, until: str) -> Dict[str, Dict[str, int]]:
    coverage: Dict[str, Dict[str, int]] = {}
    for target_date in _daterange(since, until):
        report_rows = db.get_v2_daily_report_rows(target_date)
        coverage[target_date] = {
            "report_rows": len(report_rows or []),
        }
    return coverage


def _collect_rows(since: str, until: str) -> List[Dict]:
    db = Database()
    try:
        rows = _collect_rows_from_reports(db, since, until)
        rows.extend(_collect_rows_legacy(db, since, until))
    finally:
        db.close()
    return rows


def _aggregate_by_subclass(rows: List[Dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for row in rows:
        subclass = str(row.get("subclass") or "")
        if not subclass:
            continue
        stat = out.setdefault(subclass, {"n": 0, "prog_top1_hit": 0, "prog_cover_hit": 0, "reference_hit": 0})
        stat["n"] += 1
        stat["prog_top1_hit"] += int(row.get("prog_top1_hit") or 0)
        stat["prog_cover_hit"] += int(row.get("prog_cover_hit") or 0)
        stat["reference_hit"] += int(row.get("reference_hit") or 0)
    for subclass, stat in out.items():
        n = stat["n"]
        stat["prog_top1_acc"] = stat["prog_top1_hit"] / n if n else 0.0
        stat["prog_cover_acc"] = stat["prog_cover_hit"] / n if n else 0.0
        stat["reference_acc"] = stat["reference_hit"] / n if n else 0.0
    return out


def _aggregate_by_field(rows: List[Dict], field: str) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for row in rows:
        label = str(row.get(field) or "").strip()
        if not label:
            continue
        stat = out.setdefault(label, {"n": 0, "prog_top1_hit": 0, "prog_cover_hit": 0, "reference_hit": 0})
        stat["n"] += 1
        stat["prog_top1_hit"] += int(row.get("prog_top1_hit") or 0)
        stat["prog_cover_hit"] += int(row.get("prog_cover_hit") or 0)
        stat["reference_hit"] += int(row.get("reference_hit") or 0)
    for label, stat in out.items():
        n = stat["n"]
        stat["prog_top1_acc"] = stat["prog_top1_hit"] / n if n else 0.0
        stat["prog_cover_acc"] = stat["prog_cover_hit"] / n if n else 0.0
        stat["reference_acc"] = stat["reference_hit"] / n if n else 0.0
    return out


def optimize_feedback(
    *,
    since: Union[str, date, datetime],
    until: Union[str, date, datetime],
    min_samples: int = 20,
    step: float = 0.01,
    margin: float = 0.03,
    dry_run: bool = False,
) -> Dict:
    since = _normalize_ymd(since)
    until = _normalize_ymd(until)
    rows = _collect_rows(since, until)
    config = _load_config()
    defaults = config.setdefault("defaults", {})
    defaults.setdefault("subclass", {})
    subclass_stats = _aggregate_by_subclass(rows)
    bias_stats = _aggregate_by_field(rows, "bias_type")
    source_stats = _aggregate_by_field(rows, "source")
    db = Database()
    try:
        coverage = _collect_coverage(db, since, until)
    finally:
        db.close()
    updates = []

    global_top1 = (sum(int(r.get("prog_top1_hit") or 0) for r in rows) / len(rows)) if rows else 0.0
    global_cover = (sum(int(r.get("prog_cover_hit") or 0) for r in rows) / len(rows)) if rows else 0.0
    global_reference = (sum(int(r.get("reference_hit") or 0) for r in rows) / len(rows)) if rows else 0.0

    single_gap = float(defaults.get("single_gap_threshold", 0.12))
    bias_single_bonus = float(defaults.get("bias_single_bonus", 0.12))
    bias_double_bonus = float(defaults.get("bias_double_bonus", 0.07))
    if len(rows) >= min_samples:
        if global_top1 < global_reference - margin and global_cover >= global_reference:
            new_gap = _clip(single_gap + step, 0.08, 0.18)
            if new_gap != single_gap:
                defaults["single_gap_threshold"] = round(new_gap, 4)
                updates.append(f"global.single_gap_threshold: {single_gap:.3f} -> {new_gap:.3f}")

    single_bias_stat = bias_stats.get("single") or {}
    if int(single_bias_stat.get("n") or 0) >= min_samples:
        ref = float(single_bias_stat.get("reference_acc") or 0.0)
        top1 = float(single_bias_stat.get("prog_top1_acc") or 0.0)
        cover = float(single_bias_stat.get("prog_cover_acc") or 0.0)
        if top1 < ref - margin and cover >= ref:
            new_value = _clip(bias_single_bonus - step, 0.06, 0.20)
        elif top1 > ref + margin and cover > ref + margin:
            new_value = _clip(bias_single_bonus + step, 0.06, 0.20)
        else:
            new_value = bias_single_bonus
        if new_value != bias_single_bonus:
            defaults["bias_single_bonus"] = round(new_value, 4)
            updates.append(f"global.bias_single_bonus: {bias_single_bonus:.3f} -> {new_value:.3f}")

    double_bias_stat = bias_stats.get("double") or {}
    if int(double_bias_stat.get("n") or 0) >= min_samples:
        ref = float(double_bias_stat.get("reference_acc") or 0.0)
        top1 = float(double_bias_stat.get("prog_top1_acc") or 0.0)
        cover = float(double_bias_stat.get("prog_cover_acc") or 0.0)
        if cover > ref + margin:
            new_value = _clip(bias_double_bonus + step, 0.03, 0.16)
        elif cover < ref - margin and top1 < ref - margin:
            new_value = _clip(bias_double_bonus - step, 0.03, 0.16)
        else:
            new_value = bias_double_bonus
        if new_value != bias_double_bonus:
            defaults["bias_double_bonus"] = round(new_value, 4)
            updates.append(f"global.bias_double_bonus: {bias_double_bonus:.3f} -> {new_value:.3f}")
        elif global_top1 > global_reference + margin and global_cover > global_reference + margin:
            new_gap = _clip(single_gap - step, 0.08, 0.18)
            if new_gap != single_gap:
                defaults["single_gap_threshold"] = round(new_gap, 4)
                updates.append(f"global.single_gap_threshold: {single_gap:.3f} -> {new_gap:.3f}")

    for subclass, stat in sorted(subclass_stats.items()):
        n = int(stat["n"])
        if n < min_samples:
            continue
        sub_cfg = defaults["subclass"].setdefault(subclass, {})
        top1_acc = float(stat["prog_top1_acc"])
        cover_acc = float(stat["prog_cover_acc"])
        reference_acc = float(stat["reference_acc"])

        if "info_shock" in subclass:
            current = float(sub_cfg.get("favored_bonus", 0.08))
            if top1_acc < reference_acc - margin:
                new_value = _clip(current - step, 0.04, 0.16)
            elif top1_acc > reference_acc + margin:
                new_value = _clip(current + step, 0.04, 0.16)
            else:
                new_value = current
            if new_value != current:
                sub_cfg["favored_bonus"] = round(new_value, 4)
                updates.append(f"{subclass}.favored_bonus: {current:.3f} -> {new_value:.3f}")

        if any(key in subclass for key in ["draw_shaping", "popular_", "divergence", "late_correction"]):
            current = float(sub_cfg.get("draw_bonus", 0.05))
            if cover_acc > reference_acc + margin and top1_acc < cover_acc - margin:
                new_value = _clip(current + step, 0.01, 0.18)
            elif cover_acc < reference_acc - margin and top1_acc < reference_acc - margin:
                new_value = _clip(current - step, 0.01, 0.18)
            else:
                new_value = current
            if new_value != current:
                sub_cfg["draw_bonus"] = round(new_value, 4)
                updates.append(f"{subclass}.draw_bonus: {current:.3f} -> {new_value:.3f}")

        if "popular_tax" in subclass:
            current = float(sub_cfg.get("favored_penalty", 0.04))
            if top1_acc < reference_acc - margin and cover_acc >= reference_acc:
                new_value = _clip(current + step, 0.01, 0.10)
            elif top1_acc > reference_acc + margin:
                new_value = _clip(current - step, 0.01, 0.10)
            else:
                new_value = current
            if new_value != current:
                sub_cfg["favored_penalty"] = round(new_value, 4)
                updates.append(f"{subclass}.favored_penalty: {current:.3f} -> {new_value:.3f}")

        if "popular_deepening" in subclass:
            current = float(sub_cfg.get("underdog_bonus", 0.04))
            if cover_acc > reference_acc + margin and top1_acc >= reference_acc:
                new_value = _clip(current + step, 0.01, 0.10)
            elif cover_acc < reference_acc - margin and top1_acc < reference_acc - margin:
                new_value = _clip(current - step, 0.01, 0.10)
            else:
                new_value = current
            if new_value != current:
                sub_cfg["underdog_bonus"] = round(new_value, 4)
                updates.append(f"{subclass}.underdog_bonus: {current:.3f} -> {new_value:.3f}")

    result = {
        "since": since,
        "until": until,
        "rows": len(rows),
        "global_top1_acc": round(global_top1, 4),
        "global_cover_acc": round(global_cover, 4),
        "global_reference_acc": round(global_reference, 4),
        "source_stats": {k: {"n": int(v.get("n") or 0)} for k, v in sorted(source_stats.items())},
        "bias_stats": {
            k: {
                "n": int(v.get("n") or 0),
                "prog_top1_acc": round(float(v.get("prog_top1_acc") or 0.0), 4),
                "prog_cover_acc": round(float(v.get("prog_cover_acc") or 0.0), 4),
                "reference_acc": round(float(v.get("reference_acc") or 0.0), 4),
            }
            for k, v in sorted(bias_stats.items())
        },
        "coverage": coverage,
        "updates": updates,
        "dry_run": dry_run,
    }
    if not dry_run:
        _save_config(config)
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    since = args[0] if len(args) >= 1 else (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    until = args[1] if len(args) >= 2 else datetime.now().strftime("%Y-%m-%d")
    dry_run = "--dry-run" in args
    res = optimize_feedback(since=since, until=until, dry_run=dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
