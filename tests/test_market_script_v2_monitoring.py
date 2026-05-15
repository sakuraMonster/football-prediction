import datetime

from src.db.database import Database
from src.market_script_v2.monitoring.metrics import compute_window_metrics, ewma


def test_compute_window_metrics_rate_and_magnitude():
    rows = [
        {"clv_prob": 0.01, "dispersion": 0.02},
        {"clv_prob": -0.02, "dispersion": 0.03},
        {"clv_prob": 0.03, "dispersion": 0.01},
    ]
    m = compute_window_metrics(rows)
    assert m.n == 3
    assert abs(m.clv_rate - (2 / 3)) < 1e-6
    assert abs(m.clv_magnitude - (0.01 - 0.02 + 0.03) / 3) < 1e-6
    assert m.dispersion is not None


def test_ewma_updates_with_alpha():
    assert ewma(None, 0.1, 0.2) == 0.1
    assert abs(ewma(0.1, 0.0, 0.2) - 0.08) < 1e-9


def test_database_upsert_and_fetch_v2_monitor_metric():
    db = Database("sqlite:///:memory:")

    row_id = db.upsert_v2_monitor_metric(
        subclass="info_shock_mvp",
        league="欧罗巴",
        regime="default",
        window_name="mid",
        n=200,
        clv_rate=0.56,
        clv_magnitude=0.01,
        dispersion=0.02,
        ewma_clv=0.008,
        status="white",
    )
    assert row_id is not None

    metric = db.fetch_v2_monitor_metric(
        subclass="info_shock_mvp",
        league="欧罗巴",
        regime="default",
        window_name="mid",
    )
    assert metric is not None
    assert metric.status == "white"
    assert metric.n == 200
    db.close()

