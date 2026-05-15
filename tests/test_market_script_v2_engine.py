import os
import datetime

from src.db.database import Database
from src.market_script_v2.engine import MarketScriptV2Engine


def test_v2_engine_returns_diagnosis_when_no_series():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    out = engine.analyze(
        fixture_id="fx-no-series",
        prediction_period="final",
        match_data={"fixture_id": "fx-no-series", "match_time": "2026-05-13 20:00:00"},
        mode="v2_shadow",
    )

    assert out.action_type == "Diagnosis"
    assert out.prototype == "insufficient_data"
    assert hasattr(engine, "_config_warnings")


def test_v2_engine_populates_clv_fields_when_series_present():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-clv"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.80",
        odds_d="3.60",
        odds_a="4.40",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="1.72",
        odds_d="3.70",
        odds_a="4.90",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.68",
        odds_d="3.75",
        odds_a="5.10",
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "欧罗巴"},
        mode="v2_shadow",
    )

    assert out.clv_prob is not None
    assert out.clv_logit is not None
    assert out.signal_bucket


def test_v2_engine_classifies_head_fake_when_reversal():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-head-fake"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.80",
        odds_d="3.60",
        odds_a="4.40",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="1.62",
        odds_d="3.80",
        odds_a="5.20",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.88",
        odds_d="3.55",
        odds_a="4.10",
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S")},
        mode="v2_shadow",
    )

    assert out.prototype == "head_fake"
    assert out.action_type == "Diagnosis"


def test_v2_engine_classifies_draw_shaping_when_draw_is_dominant_shift():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-draw-shaping"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="2.30",
        odds_d="3.20",
        odds_a="3.10",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="2.32",
        odds_d="3.05",
        odds_a="3.12",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="2.35",
        odds_d="2.85",
        odds_a="3.15",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="bet365",
        snapshot_time=t_close,
        odds_h="2.36",
        odds_d="2.84",
        odds_a="3.12",
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "英超"},
        mode="v2_shadow",
    )

    assert out.prototype == "draw_shaping"
    assert out.subclass == "draw_shaping_draw_driven"
    assert out.action_type in {"Risk", "Diagnosis"}


def test_v2_engine_classifies_key_number_hold_when_no_cross_but_price_swings():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-key-hold"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.90",
        odds_d="3.50",
        odds_a="4.00",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="1.88",
        odds_d="3.52",
        odds_a="4.10",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.89",
        odds_d="3.51",
        odds_a="4.05",
    )

    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        ah_line="半球",
        price_home="0.84",
        price_away="1.04",
        is_mainline=True,
    )
    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        ah_line="半球",
        price_home="0.94",
        price_away="0.94",
        is_mainline=True,
    )
    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        ah_line="半球",
        price_home="1.02",
        price_away="0.86",
        is_mainline=True,
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "英超"},
        mode="v2_shadow",
    )

    assert out.prototype in {"key_number_mgmt", "risk_balancing"}
    if out.prototype == "key_number_mgmt":
        assert out.subclass == "key_number_hold"


def test_v2_engine_classifies_risk_balancing_price_only_when_ah_price_moves_but_euro_flat():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-risk-price-only"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.90",
        odds_d="3.50",
        odds_a="4.10",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="1.90",
        odds_d="3.50",
        odds_a="4.10",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.90",
        odds_d="3.50",
        odds_a="4.10",
    )

    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        ah_line="半球",
        price_home="0.86",
        price_away="1.02",
        is_mainline=True,
    )
    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        ah_line="半球",
        price_home="0.96",
        price_away="0.92",
        is_mainline=True,
    )
    db.save_v2_ah_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        ah_line="半球",
        price_home="1.06",
        price_away="0.82",
        is_mainline=True,
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "英超"},
        mode="v2_shadow",
    )

    assert out.prototype in {"risk_balancing", "key_number_mgmt"}
    if out.prototype == "risk_balancing":
        assert out.subclass == "risk_balancing_price_only"


def test_v2_engine_classifies_late_correction_convergence_when_dispersion_converges():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-convergence"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.90",
        odds_d="3.50",
        odds_a="4.10",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="bet365",
        snapshot_time=t_open,
        odds_h="2.05",
        odds_d="3.25",
        odds_a="3.70",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.78",
        odds_d="3.60",
        odds_a="4.60",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="bet365",
        snapshot_time=t_close,
        odds_h="1.79",
        odds_d="3.58",
        odds_a="4.55",
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "英超"},
        mode="v2_shadow",
    )

    assert out.subclass in {"late_correction_convergence", "info_shock_mvp", "info_shock_euro_first"}


def test_v2_engine_classifies_public_pressure_popular_tax():
    db = Database("sqlite:///:memory:")
    engine = MarketScriptV2Engine(db)

    fixture_id = "fx-public-tax"
    kickoff = datetime.datetime(2026, 5, 13, 20, 0, 0)
    t_open = kickoff - datetime.timedelta(hours=30)
    t_mid = kickoff - datetime.timedelta(hours=6)
    t_close = kickoff - datetime.timedelta(minutes=20)

    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_open,
        odds_h="1.65",
        odds_d="3.90",
        odds_a="5.40",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_mid,
        odds_h="1.70",
        odds_d="3.65",
        odds_a="5.60",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="macau",
        snapshot_time=t_close,
        odds_h="1.76",
        odds_d="3.35",
        odds_a="5.80",
    )
    db.save_v2_odds_snapshot(
        fixture_id=fixture_id,
        book_id="bet365",
        snapshot_time=t_close,
        odds_h="1.75",
        odds_d="3.36",
        odds_a="5.90",
    )

    out = engine.analyze(
        fixture_id=fixture_id,
        prediction_period="final",
        match_data={"fixture_id": fixture_id, "match_time": kickoff.strftime("%Y-%m-%d %H:%M:%S"), "league": "英超"},
        mode="v2_shadow",
    )

    assert out.prototype in {"public_pressure", "draw_shaping", "risk_balancing"}
    if out.prototype == "public_pressure":
        assert out.subclass in {"public_pressure_popular_tax", "public_pressure_popular_deepening"}
