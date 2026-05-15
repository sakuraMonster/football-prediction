from src.db.database import Database


def test_save_prediction_accepts_non_string_llm_prediction(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_url=f"sqlite:///{db_path}")

    ok = db.save_prediction(
        {
            "fixture_id": "f1",
            "match_num": "周二001",
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "match_time": "2026-05-13 20:00",
            "llm_prediction": {"text": "### 竞彩推荐：胜"},
        },
        period="final",
    )
    assert ok is True
    row = db.get_prediction_by_period("f1", "final")
    assert row is not None
    assert row.prediction_text
    db.close()


def test_save_prediction_raw_data_datetime_is_json_safe(tmp_path):
    from datetime import datetime

    db_path = tmp_path / "test.db"
    db = Database(db_url=f"sqlite:///{db_path}")

    ok = db.save_prediction(
        {
            "fixture_id": "f2",
            "match_num": "周二002",
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "match_time": datetime(2026, 5, 13, 18, 0, 0),
            "llm_prediction": "### 竞彩推荐：胜",
        },
        period="final",
    )
    assert ok is True
    row = db.get_prediction_by_period("f2", "final")
    assert row is not None
    assert isinstance(row.raw_data, dict)
    assert isinstance(row.raw_data.get("match_time"), str)
    db.close()
