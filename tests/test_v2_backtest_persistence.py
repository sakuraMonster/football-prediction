import sqlite3

from src.db.database import Database


def test_v2_backtest_persistence_roundtrip(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_url=f"sqlite:///{db_path}")

    run_id = db.create_v2_backtest_run(
        run_tag="historical",
        since=None,
        until=None,
        limit=10,
        min_books=5,
        total_fixtures=3,
        evaluated=2,
        skipped=1,
        fixtures_with_ah=1,
    )
    assert isinstance(run_id, int)
    assert run_id > 0

    n = db.bulk_insert_v2_backtest_rows(
        run_id,
        [
            {
                "fixture_id": "f1",
                "league": "L",
                "kickoff": "2026-05-01 12:00",
                "prototype": "info_shock",
                "subclass": "info_shock_mvp",
                "action_type": "Risk",
                "strength": "medium",
                "signal_bucket": "close",
                "clv_prob": 0.01,
                "clv_logit": 0.02,
                "dispersion": 0.03,
                "favored_side": "home",
                "actual_result": "胜",
                "favored_win": True,
                "why": "ok",
            },
            {
                "fixture_id": "f2",
                "league": "L",
                "kickoff": "2026-05-02 12:00",
                "prototype": "risk_balancing",
                "subclass": "drift",
                "action_type": "Risk",
                "strength": "weak",
                "signal_bucket": "close",
                "clv_prob": -0.01,
                "clv_logit": -0.02,
                "dispersion": 0.05,
                "favored_side": "away",
                "actual_result": None,
                "favored_win": None,
                "why": None,
            },
        ],
    )
    assert n == 2
    db.close()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM v2_backtest_runs")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(1) FROM v2_backtest_rows")
    assert cur.fetchone()[0] == 2
    conn.close()

