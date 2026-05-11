import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta


def _load_micro_rule_ids(base_dir):
    path = os.path.join(base_dir, "data", "rules", "micro_signals.json")
    with open(path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    return {str(r.get("id")) for r in rules if r.get("id")}


def _date_window(date_str):
    ws = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, minute=0, second=0)
    we = ws + timedelta(days=1)
    return ws, we


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, base_dir)
    from src.llm.predictor import LLMPredictor

    db_path = os.path.join(base_dir, "data", "football.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    ws, we = _date_window(args.date)
    cur.execute(
        """
        SELECT fixture_id, match_num, home_team, away_team, match_time, prediction_period, raw_data, prediction_text
        FROM match_predictions
        WHERE match_time >= ? AND match_time < ?
        ORDER BY match_time ASC
        """,
        (ws.strftime("%Y-%m-%d %H:%M:%S"), we.strftime("%Y-%m-%d %H:%M:%S")),
    )
    rows = cur.fetchall()

    priority = {"repredicted": 5, "final": 3, "pre_12h": 2, "pre_24h": 1, "historical": 0}
    by_fixture = {}
    for r in rows:
        fid = r[0]
        if fid not in by_fixture or priority.get(r[5], 0) > priority.get(by_fixture[fid][5], 0):
            by_fixture[fid] = r
    records = list(by_fixture.values())

    known_ids = _load_micro_rule_ids(base_dir)
    id_pat = re.compile(r"\[([\w_]+)\]")

    removed_counter = {}
    added_counter = {}
    diffs = []

    for fid, match_num, home, away, match_time, period, raw_data, pred_text in records:
        stored_ids = set(id_pat.findall(pred_text or "")) & known_ids
        data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
        odds = data.get("odds", {}) if isinstance(data, dict) else {}
        asian = data.get("asian_odds", {}) if isinstance(data, dict) else {}
        league = data.get("league", "") if isinstance(data, dict) else ""
        euro_odds = (data.get("europe_odds") if isinstance(data, dict) else None) or []
        recomputed_text = LLMPredictor._analyze_micro_market_signals(odds, asian, league, euro_odds=euro_odds)
        recomputed_ids = set(id_pat.findall(recomputed_text or "")) & known_ids

        removed = sorted(list(stored_ids - recomputed_ids))
        added = sorted(list(recomputed_ids - stored_ids))
        if removed or added:
            diffs.append(
                {
                    "match_num": match_num,
                    "home": home,
                    "away": away,
                    "period": period,
                    "removed": removed,
                    "added": added,
                }
            )
            for rid in removed:
                removed_counter[rid] = removed_counter.get(rid, 0) + 1
            for rid in added:
                added_counter[rid] = added_counter.get(rid, 0) + 1

    print(f"date_window={args.date} 12:00~next 12:00")
    print(f"unique_fixtures={len(records)}")
    print(f"diff_matches={len(diffs)}")

    if removed_counter:
        print("")
        print("removed_rule_counts:")
        for k in sorted(removed_counter, key=lambda x: (-removed_counter[x], x)):
            print(f"  {k}: {removed_counter[k]}")

    if added_counter:
        print("")
        print("added_rule_counts:")
        for k in sorted(added_counter, key=lambda x: (-added_counter[x], x)):
            print(f"  {k}: {added_counter[k]}")

    if diffs:
        print("")
        for d in diffs:
            print(f"{d['match_num']} {d['home']} vs {d['away']} | period={d['period']} | -{','.join(d['removed']) if d['removed'] else 'none'} | +{','.join(d['added']) if d['added'] else 'none'}")


if __name__ == "__main__":
    main()
