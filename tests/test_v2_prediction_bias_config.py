from src.market_script_v2.bias_config import load_v2_prediction_bias_params


def test_load_v2_prediction_bias_params_defaults(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        '{"version":1,"defaults":{"lean_draw":{"draw_dom_delta_abs_min":0.02,"close_dispersion_max":0.08,"draw_prob_delta_min":0.015,"p_draw_close_min":0.28,"favored_prob_delta_max":0.0},"guard_draw":{"draw_prob_delta_min":0.01,"favored_prob_delta_max":-0.01},"two_heads":{"draw_prob_delta_max":-0.01,"p_draw_close_max":0.23}},"overrides":[]}',
        encoding="utf-8",
    )
    p = load_v2_prediction_bias_params(league="英超", dispersion_close=0.05, path=str(cfg))
    assert p.lean_draw.p_draw_close_min == 0.28
    assert p.two_heads.p_draw_close_max == 0.23


def test_load_v2_prediction_bias_params_override_by_league(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        '{"version":1,"defaults":{"lean_draw":{"draw_dom_delta_abs_min":0.02,"close_dispersion_max":0.08,"draw_prob_delta_min":0.015,"p_draw_close_min":0.28,"favored_prob_delta_max":0.0},"guard_draw":{"draw_prob_delta_min":0.01,"favored_prob_delta_max":-0.01},"two_heads":{"draw_prob_delta_max":-0.01,"p_draw_close_max":0.23}},"overrides":[{"match":{"league_contains":["日职"],"dispersion_close_max":0.07},"params":{"lean_draw":{"p_draw_close_min":0.27}}}]}',
        encoding="utf-8",
    )
    p1 = load_v2_prediction_bias_params(league="日职", dispersion_close=0.06, path=str(cfg))
    assert p1.lean_draw.p_draw_close_min == 0.27
    p2 = load_v2_prediction_bias_params(league="日职", dispersion_close=0.09, path=str(cfg))
    assert p2.lean_draw.p_draw_close_min == 0.28

