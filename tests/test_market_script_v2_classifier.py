from src.market_script_v2.classifier import MatchFeatures, select_best_subclass
from src.market_script_v2.config import load_v2_subclass_configs


def test_select_best_subclass_prefers_more_specific_detection():
    cfg = load_v2_subclass_configs()

    features = MatchFeatures(
        prototype="info_shock",
        subclass="info_shock_mvp",
        favored_side="home",
        euro_favored_prob_delta=0.04,
        draw_prob_delta=0.0,
        dispersion_open=0.02,
        dispersion_close=0.02,
        convergence_flag=False,
        who_moves_first="euro_first",
        velocity="fast",
        ah_line_cross=False,
        ah_price_swing=0.02,
        reversal_flag=False,
    )

    best = select_best_subclass(cfg, features)
    assert best is not None
    assert best.subclass_id in {"info_shock_euro_first", "info_shock_mvp"}
