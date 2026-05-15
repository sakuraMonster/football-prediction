from datetime import datetime

from src.db.database import Database
from src.market_script_v2.daily_window import compute_today_window


def test_compute_today_window_definition():
    now = datetime(2026, 5, 13, 13, 0, 0)
    start, end, tag = compute_today_window(now)
    assert start == datetime(2026, 5, 13, 12, 0, 0)
    assert end == datetime(2026, 5, 14, 12, 0, 0)
    assert tag == "2026-05-13_12"

    now2 = datetime(2026, 5, 13, 9, 0, 0)
    start2, end2, tag2 = compute_today_window(now2)
    assert start2 == datetime(2026, 5, 12, 12, 0, 0)
    assert end2 == datetime(2026, 5, 13, 12, 0, 0)
    assert tag2 == "2026-05-12_12"


def test_upsert_and_fetch_daily_fixtures(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_url=f"sqlite:///{db_path}")

    start = datetime(2026, 5, 13, 12, 0, 0)
    end = datetime(2026, 5, 14, 12, 0, 0)
    tag = "2026-05-13_12"

    saved = db.upsert_v2_daily_fixtures(
        window_tag=tag,
        window_start=start,
        window_end=end,
        fixtures=[
            {
                "fixture_id": "f1",
                "match_num": "周三001",
                "league": "L",
                "home_team": "A",
                "away_team": "B",
                "kickoff_time": "2026-05-13 20:00",
            },
            {
                "fixture_id": "f2",
                "match_num": "周四001",
                "league": "L",
                "home_team": "C",
                "away_team": "D",
                "kickoff_time": "2026-05-14 01:00",
            },
        ],
        source="jingcai",
    )
    assert saved == 2

    rows = db.fetch_v2_daily_fixtures(tag)
    assert len(rows) == 2
    assert {r["fixture_id"] for r in rows} == {"f1", "f2"}

    saved2 = db.upsert_v2_daily_fixtures(
        window_tag=tag,
        window_start=start,
        window_end=end,
        fixtures=[
            {
                "fixture_id": "f1",
                "league": "L2",
                "kickoff_time": "2026-05-13 20:05",
            }
        ],
    )
    assert saved2 == 1
    rows2 = db.fetch_v2_daily_fixtures(tag)
    f1 = [r for r in rows2 if r["fixture_id"] == "f1"][0]
    assert f1["league"] == "L2"
    db.close()

