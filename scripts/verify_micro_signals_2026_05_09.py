import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _pct_drop(init_value, live_value):
    if init_value in (None, 0) or live_value is None:
        return None
    return (init_value - live_value) / init_value * 100.0


def _pick_company(europe_odds, keyword):
    for row in europe_odds or []:
        if keyword in str(row.get("company", "")):
            return row
    return None


def _parse_asian_line(line):
    handicap_map = {
        "平手": 0,
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
    }
    parts = (line or "").split("|")
    if len(parts) < 3:
        return None
    w1 = _to_float(parts[0].strip().replace("↑", "").replace("↓", ""))
    h = parts[1].strip().replace(" ", "")
    w2 = _to_float(parts[2].strip().replace("↑", "").replace("↓", ""))
    hv = handicap_map.get(h)
    if w1 is None or w2 is None or hv is None:
        return None
    return {"w1": w1, "w2": w2, "h": h, "hv": hv}


def _giving_side_from_macau(asian_odds):
    macau = (asian_odds or {}).get("macau", {}) if isinstance(asian_odds, dict) else {}
    start = _parse_asian_line(macau.get("start", ""))
    live = _parse_asian_line(macau.get("live", ""))
    if not start or not live:
        return None
    hs = start["hv"]
    return "home" if hs >= 0 else "away"


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, base_dir)
    from src.llm.predictor import LLMPredictor

    db_path = os.path.join(base_dir, "data", "football.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    target_date = "2026-05-09"
    ws = datetime.strptime(target_date, "%Y-%m-%d").replace(hour=12, minute=0, second=0)
    we = ws + timedelta(days=1)

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

    rule_pat = re.compile(r"\[([\w_]+)\]")

    target_rules = {"away_odds_drop_over5pct_trap", "micro_002"}
    matched = []
    for fid, match_num, home, away, match_time, period, raw_data, pred_text in records:
        ids = set(rule_pat.findall(pred_text or ""))
        hit = sorted(list(ids & target_rules))
        if not hit:
            continue
        data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
        odds = data.get("odds", {}) if isinstance(data, dict) else {}
        nspf = odds.get("nspf") if isinstance(odds, dict) else None
        live_away_nspf = _to_float(nspf[2]) if (isinstance(nspf, list) and len(nspf) > 2) else None
        details = LLMPredictor.parse_prediction_details(pred_text or "")
        recomputed_text = LLMPredictor._analyze_micro_market_signals(
            odds,
            data.get("asian_odds", {}) if isinstance(data, dict) else {},
            data.get("league", "") if isinstance(data, dict) else "",
            euro_odds=(data.get("europe_odds") if isinstance(data, dict) else None) or [],
        )
        recomputed_ids = set(rule_pat.findall(recomputed_text or ""))

        europe_odds = data.get("europe_odds") or []
        mac = _pick_company(europe_odds, "澳门")
        bet365 = _pick_company(europe_odds, "Bet365") or _pick_company(europe_odds, "bet365")

        mac_init_away = _to_float(mac.get("init_away")) if mac else None
        mac_live_away = _to_float(mac.get("live_away")) if mac else None
        bet_init_away = _to_float(bet365.get("init_away")) if bet365 else None
        bet_live_away = _to_float(bet365.get("live_away")) if bet365 else None

        asian_odds = data.get("asian_odds") if isinstance(data, dict) else None
        giving_side = _giving_side_from_macau(asian_odds)

        matched.append(
            {
                "match_num": match_num,
                "home": home,
                "away": away,
                "match_time": match_time,
                "period": period,
                "hit_rules": hit,
                "recomputed_hit_rules": sorted(list(recomputed_ids & target_rules)),
                "recommendation_rq": details.get("recommendation_rq", "暂无"),
                "giving_side": giving_side,
                "macau_init_away": mac_init_away,
                "macau_live_away": mac_live_away,
                "bet365_init_away": bet_init_away,
                "bet365_live_away": bet_live_away,
                "nspf_live_away": live_away_nspf,
                "drop_pct_macau_init_vs_macau_live": _pct_drop(mac_init_away, mac_live_away),
                "drop_pct_bet365_init_vs_bet365_live": _pct_drop(bet_init_away, bet_live_away),
                "drop_pct_macau_init_vs_nspf_live_away": _pct_drop(mac_init_away, live_away_nspf),
            }
        )

    print(f"date_window={target_date} 12:00~next 12:00")
    print(f"unique_fixtures={len(records)}")
    print(f"matched_target_rules={len(matched)}")

    for it in matched:
        print("")
        print(f"{it['match_num']} {it['home']} vs {it['away']} | period={it['period']} | stored_hit={','.join(it['hit_rules'])} | recomputed_hit={','.join(it['recomputed_hit_rules'])}")
        if "micro_002" in it["hit_rules"]:
            print(f"  giving_side={it['giving_side']} recommendation_rq={it['recommendation_rq']}")
        print(f"  macau away init={it['macau_init_away']} live={it['macau_live_away']} drop%={None if it['drop_pct_macau_init_vs_macau_live'] is None else round(it['drop_pct_macau_init_vs_macau_live'],3)}")
        print(f"  bet365 away init={it['bet365_init_away']} live={it['bet365_live_away']} drop%={None if it['drop_pct_bet365_init_vs_bet365_live'] is None else round(it['drop_pct_bet365_init_vs_bet365_live'],3)}")
        print(f"  code_live_away(nspf[2])={it['nspf_live_away']} drop%_vs_macau_init={None if it['drop_pct_macau_init_vs_nspf_live_away'] is None else round(it['drop_pct_macau_init_vs_nspf_live_away'],3)}")


if __name__ == "__main__":
    main()
