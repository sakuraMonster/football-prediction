import argparse
import json
import os
import sqlite3


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", nargs="+", required=True)
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "football.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    for match_num in args.matches:
        cur.execute(
            """
            SELECT match_num, home_team, away_team, match_time, prediction_period, raw_data
            FROM match_predictions
            WHERE match_num = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (match_num,),
        )
        row = cur.fetchone()
        if not row:
            print(f"{match_num}: not found")
            continue
        mn, home, away, match_time, period, raw = row
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        euro = data.get("europe_odds") or []
        mac = _pick_company(euro, "澳门") or {}
        init_h = _to_float(mac.get("init_home"))
        init_d = _to_float(mac.get("init_draw"))
        init_a = _to_float(mac.get("init_away"))
        live_h = _to_float(mac.get("live_home"))
        live_d = _to_float(mac.get("live_draw"))
        live_a = _to_float(mac.get("live_away"))
        dh = _pct_drop(init_h, live_h)
        da = _pct_drop(init_a, live_a)
        print("")
        print(f"{mn} {home} vs {away} | period={period} | time={match_time}")
        print(f"  macau init: H={init_h} D={init_d} A={init_a}")
        print(f"  macau live: H={live_h} D={live_d} A={live_a}")
        print(f"  drop%: home={None if dh is None else round(dh,3)} away={None if da is None else round(da,3)}")


if __name__ == "__main__":
    main()

