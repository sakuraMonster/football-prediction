from src.llm.predictor import LLMPredictor
from datetime import datetime, timedelta
import tempfile
from pathlib import Path


def _make_predictor():
    return object.__new__(LLMPredictor)


def test_load_arbitration_rules_reads_enabled_rules():
    predictor = _make_predictor()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "arbitration_rules.json"
        path.write_text(
            '[{"id":"disabled_rule","enabled":false,"priority":999},{"id":"information_vacuum_abort","enabled":true,"priority":100}]',
            encoding="utf-8",
        )
        original = LLMPredictor._get_arbitration_rules_path if hasattr(LLMPredictor, "_get_arbitration_rules_path") else None
        LLMPredictor._get_arbitration_rules_path = lambda self: str(path)
        try:
            rules = predictor._load_arbitration_rules()
        finally:
            if original:
                LLMPredictor._get_arbitration_rules_path = original
            else:
                delattr(LLMPredictor, "_get_arbitration_rules_path")

    assert len(rules) == 1
    assert rules[0]["id"] == "information_vacuum_abort"


def test_load_arbitration_rules_normalizes_natural_language_action_type():
    predictor = _make_predictor()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "arbitration_rules.json"
        path.write_text(
            '[{"id":"draft_rule","enabled":true,"priority":90,"action_type":"若基本面无明确反对，应优先考虑主队不败甚至主胜方向。禁止仅凭盘赔结构解释推翻基本面。","action_payload":{},"condition":"ctx[\'informative_dimension_count\'] >= 0"}]',
            encoding="utf-8",
        )
        original = LLMPredictor._get_arbitration_rules_path if hasattr(LLMPredictor, "_get_arbitration_rules_path") else None
        LLMPredictor._get_arbitration_rules_path = lambda self: str(path)
        try:
            rules = predictor._load_arbitration_rules()
        finally:
            if original:
                LLMPredictor._get_arbitration_rules_path = original
            else:
                delattr(LLMPredictor, "_get_arbitration_rules_path")

    assert rules[0]["action_type"] == "forbid_override"


def test_evaluate_arbitration_rules_aborts_on_information_vacuum():
    predictor = _make_predictor()
    predictor._load_arbitration_rules = lambda: [
        {
            "id": "information_vacuum_abort",
            "priority": 100,
            "condition": "ctx['informative_dimension_count'] < 2",
            "action_type": "abort_prediction",
            "action_payload": {"message": "信息不足以形成预测，建议回避", "confidence": 0},
            "enabled": True,
        }
    ]

    result = predictor._evaluate_arbitration_rules({"informative_dimension_count": 1})

    assert result["abort_prediction"] is True
    assert result["message"] == "信息不足以形成预测，建议回避"
    assert result["confidence_cap"] == 0


def test_evaluate_arbitration_rules_allows_prediction_when_two_dimensions_are_informative():
    predictor = _make_predictor()
    predictor._load_arbitration_rules = lambda: [
        {
            "id": "information_vacuum_abort",
            "priority": 100,
            "condition": "ctx['informative_dimension_count'] < 2",
            "action_type": "abort_prediction",
            "action_payload": {"message": "信息不足以形成预测，建议回避", "confidence": 0},
            "enabled": True,
        }
    ]

    result = predictor._evaluate_arbitration_rules({"informative_dimension_count": 2})

    assert result["abort_prediction"] is False


def test_evaluate_arbitration_rules_supports_legacy_asian_name_in_condition():
    predictor = _make_predictor()
    predictor._load_arbitration_rules = lambda: [
        {
            "id": "legacy_asian_rule",
            "priority": 95,
            "condition": "asian['start_hv'] == 0.25 and asian['live_hv'] == 0.0 and asian['giving_live_w'] <= 0.80",
            "action_type": "forbid_override",
            "action_payload": {},
            "explanation_template": "兼容旧版 asian 条件",
            "enabled": True,
        }
    ]

    result = predictor._evaluate_arbitration_rules(
        {"asian": {"start_hv": 0.25, "live_hv": 0.0, "giving_live_w": 0.78}}
    )

    assert result["override_blocked"] is True
    assert "兼容旧版 asian 条件" in result["guard_messages"]


def test_evaluate_arbitration_rules_blocks_override_when_market_and_micro_align():
    predictor = _make_predictor()
    predictor._load_arbitration_rules = lambda: [
        {
            "id": "weak_evidence_cannot_override_market",
            "priority": 90,
            "condition": "ctx['market_micro_aligned'] is True and ctx['reverse_only_from_fundamental_or_intel'] is True",
            "action_type": "forbid_override",
            "action_payload": {"blocked_dimensions": ["基本面", "情报"]},
            "enabled": True,
        }
    ]

    result = predictor._evaluate_arbitration_rules(
        {
            "market_micro_aligned": True,
            "reverse_only_from_fundamental_or_intel": True,
        }
    )

    assert result["override_blocked"] is True
    assert any("弱证据" in msg or "推翻" in msg for msg in result["guard_messages"])


def test_build_arbitration_rule_context_includes_asian_shape():
    asian = {
        "macau": {
            "start": "1.06 | 平手/半球 | 0.78",
            "live": "0.78 | 平手 | 1.06",
        }
    }

    ctx = LLMPredictor._build_arbitration_rule_context(
        details={"arb_market": "胜", "arb_micro": "胜", "arb_final": "胜"},
        conflict_assessment={},
        triggered_rule_ids=[],
        asian_context=LLMPredictor._build_micro_rule_asian_context(asian),
    )

    assert ctx["asian"]["start_hv"] == 0.25
    assert ctx["asian"]["live_hv"] == 0.0
    assert ctx["asian"]["giving_live_w"] == 0.78


def test_apply_arbitration_actions_returns_skip_text_when_abort_prediction():
    predictor = _make_predictor()
    text = "## 🎯 最终预测\n- **竞彩推荐**：胜(55%)/平(45%)\n- **竞彩让球推荐**：让平(55%)/让胜(45%)\n- **竞彩置信度**：58"
    details = {"confidence": "58"}
    actions = {
        "abort_prediction": True,
        "message": "信息不足以形成预测，建议回避",
        "confidence_cap": 0,
    }

    new_text, changed = predictor._apply_arbitration_actions(text, details, actions)

    assert changed is True
    assert "信息不足以形成预测，建议回避" in new_text
    assert "暂无有效预测（建议回避）" in new_text
    assert "竞彩置信度**：0" in new_text


def test_arbitration_rules_seed_contains_information_vacuum_abort():
    predictor = _make_predictor()
    rules = predictor._load_arbitration_rules()
    info_rule = next(rule for rule in rules if rule["id"] == "information_vacuum_abort")
    assert info_rule["enabled"] is True
    assert info_rule["condition"] == "ctx['informative_dimension_count'] < 2"
    assert any(rule["id"] == "weak_evidence_cannot_override_market" for rule in rules)
    assert any(rule["id"] == "pk025_drop_to_pk_low_water_support_home" for rule in rules)


def test_build_risk_policy_prefers_stricter_confidence_cap():
    policy = LLMPredictor._build_risk_policy(
        triggered_rule_ids=["micro_rule_01"],
        odds_conflict_text="存在欧亚冲突",
        has_anchor_divergence=True,
    )

    assert policy["must_cover_micro_signals"] is True
    assert policy["must_double_nspf"] is True
    assert policy["must_double_rq"] is True
    assert policy["must_explain_market_anchor"] is True
    assert policy["confidence_cap"] == 60


def test_build_retry_messages_enforces_market_anchor_and_caps():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": False,
        "must_double_nspf": True,
        "must_double_rq": True,
        "must_explain_market_anchor": True,
        "confidence_cap": 60,
    }
    details = {
        "analysis_panpei": "机构诱上，但文本未解释市场锚点。",
        "recommendation_nspf": "负",
        "recommendation_rq": "让负",
        "confidence": "80",
    }
    match_asian_odds = {
        "macau": {
            "start": "0.82 | 半球 | 1.02",
            "live": "0.96 | 半球 | 0.86",
        }
    }

    msgs = predictor._build_retry_messages(
        result_text="这里只写了最终推荐，没有写市场锚点。",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds=match_asian_odds,
        triggered_rule_ids=[],
    )

    assert any("亚赔实际让球方" in msg for msg in msgs)
    assert any("不让球推荐必须双选" in msg for msg in msgs)
    assert any("竞彩让球推荐必须双选" in msg for msg in msgs)
    assert any("60 或以下" in msg for msg in msgs)


def test_build_retry_messages_requires_micro_signal_match_line_when_triggered():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": True,
        "must_double_nspf": False,
        "must_double_rq": False,
        "must_explain_market_anchor": False,
        "confidence_cap": None,
    }
    details = {
        "analysis_panpei": "机构诱上，并回应了 [R205]。",
        "recommendation_nspf": "平(55%)/负(45%)",
        "recommendation_rq": "让负(60%)/让平(40%)",
        "confidence": "58",
    }

    msgs = predictor._build_retry_messages(
        result_text="测试文本",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds={"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球 | 0.86"}},
        triggered_rule_ids=["R205"],
    )

    assert any("盘赔微观信号规则匹配" in msg for msg in msgs)


def test_build_retry_messages_requires_no_match_line_when_no_micro_signal_triggered():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": False,
        "must_double_nspf": False,
        "must_double_rq": False,
        "must_explain_market_anchor": False,
        "confidence_cap": None,
    }
    details = {
        "analysis_panpei": "机构以浅盘控热为主，当前未见明显诱导。",
        "recommendation_nspf": "胜(55%)/平(45%)",
        "recommendation_rq": "让平(55%)/让胜(45%)",
        "confidence": "58",
    }

    msgs = predictor._build_retry_messages(
        result_text="测试文本",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds={"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球 | 0.86"}},
        triggered_rule_ids=[],
    )

    assert any("无盘赔微观信号规则匹配" in msg for msg in msgs)


def test_format_signal_with_prediction_bias_infers_nspf_bias():
    asian_home_give = {"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球 | 0.86"}}
    asian_away_give = {"macau": {"start": "1.02 | 受半球 | 0.82", "live": "0.94 | 受半球 | 0.90"}}

    text_one = "【欧赔骤降陷阱】主胜赔率异常下降，请重点防范主队不胜（平/负）。"
    text_two = "检测到让球方可能确实强势，切莫轻易反向选择。"

    assert LLMPredictor._format_signal_with_prediction_bias(text_one, asian_home_give).endswith("【预测偏向：平负】")
    assert LLMPredictor._format_signal_with_prediction_bias(text_two, asian_away_give).endswith("【预测偏向：负】")


def test_extract_odds_data_surfaces_prediction_bias_for_signals():
    predictor = _make_predictor()
    predictor._analyze_micro_market_signals = lambda odds, asian, league, euro_odds=None: "🔴 [R1] 测试信号：请重点防范主队不胜（平/负）。"
    predictor._detect_deep_water_trap = lambda asian: "机构真实看好主队，主胜必须进入核心推荐。"
    predictor._detect_half_ball_trap = lambda asian, odds: ""
    predictor._detect_handicap_water_divergence = lambda asian: ""
    predictor._detect_shallow_water_trap = lambda asian, odds: ""
    predictor._detect_euro_asian_divergence = lambda odds, asian, europe_odds=None: ""
    predictor._detect_shallow_showweak_induce_down = lambda asian: ""
    predictor._build_market_anchor_summary = lambda match_data: {
        "text": "亚赔实际让球方/上盘 = 主队；欧赔实力方 = 主队。"
    }
    predictor._format_leisu_intelligence_block = lambda match_data: []

    text = predictor._extract_odds_data(
        {
            "league": "欧联",
            "odds": {"nspf": ["1.80", "3.40", "4.10"]},
            "asian_odds": {"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球 | 0.86"}},
            "europe_odds": [],
        }
    )

    assert "预测偏向：平负" in text
    assert "预测偏向：胜" in text


def test_build_retry_messages_requires_four_dimension_arbitration_block():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": False,
        "must_double_nspf": False,
        "must_double_rq": False,
        "must_explain_market_anchor": False,
        "confidence_cap": None,
    }
    details = {
        "analysis_panpei": "盘赔微观信号规则匹配：无盘赔微观信号规则匹配。\n机构浅盘控热，暂未形成强诱导。",
        "analysis_arbitration": "",
        "recommendation_nspf": "胜(55%)/平(45%)",
        "recommendation_rq": "让平(55%)/让胜(45%)",
        "confidence": "58",
    }

    msgs = predictor._build_retry_messages(
        result_text="测试文本",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds={"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球 | 0.86"}},
        triggered_rule_ids=[],
    )

    assert any("【四维仲裁】" in msg for msg in msgs)


def test_build_programmatic_arbitration_hint_surfaces_program_evidence():
    predictor = _make_predictor()
    match_data = {
        "home_team": "弗赖堡",
        "away_team": "布拉加",
        "odds": {"nspf": ["1.62", "3.50", "4.42"]},
        "asian_odds": {"macau": {"start": "0.88 | 半球 | 0.98", "live": "0.96 | 半球/一球 | 0.86"}},
        "europe_odds": [{"company": "澳门", "init_home": "1.70", "init_away": "4.60"}],
        "leisu_intelligence": {
            "home": {"pros": ["主场强势"], "cons": ["防守不稳"]},
            "away": {"pros": ["首回合领先"], "cons": ["防线伤停严重", "客场守成差"]},
            "neutral": ["两回合淘汰赛"],
        },
    }
    risk_policy = {
        "must_cover_micro_signals": True,
        "must_double_nspf": True,
        "must_double_rq": True,
        "must_explain_market_anchor": True,
        "confidence_cap": 60,
    }

    hint = predictor._build_programmatic_arbitration_hint(
        match_data=match_data,
        risk_policy=risk_policy,
        triggered_rule_ids=["R205"],
        micro_signals_text="[R205] 升盘升水，防主胜",
        odds_conflict_text="欧亚存在方向分工",
        has_anchor_divergence=True,
    )

    assert "程序化仲裁参考" in hint
    assert "亚赔实际让球方" in hint
    assert "欧赔实力方" in hint
    assert "[R205]" in hint
    assert "情报数量分布" in hint


def test_extract_structured_block_reads_agent_summary_fields():
    text = """正文内容
[A_STRUCTURED]
fundamental_side: 主队优势
motivation_bias: 主队更强
injury_bias: 客队受损
intel_bias: 主队受支持
nspf_tilt: 胜平
[/A_STRUCTURED]
"""
    summary = LLMPredictor._extract_structured_block(text, "A_STRUCTURED")

    assert summary["fundamental_side"] == "主队优势"
    assert summary["motivation_bias"] == "主队更强"
    assert summary["nspf_tilt"] == "胜平"


def test_build_agent_structured_summaries_combines_a_and_b_blocks():
    agent_a = """A正文
[A_STRUCTURED]
fundamental_side: 主队优势
motivation_bias: 主队更强
injury_bias: 客队受损
intel_bias: 主队受支持
nspf_tilt: 胜平
[/A_STRUCTURED]"""
    agent_b = """B正文
[B_STRUCTURED]
market_side: 让球方
market_intent: 诱上
intel_support: 支持受让方
micro_bias: 主队不胜
nspf_tilt: 平负
[/B_STRUCTURED]"""
    text = LLMPredictor._build_agent_structured_summaries(agent_a, agent_b)

    assert "Agent A 结构化摘要" in text
    assert "fundamental_side = 主队优势" in text
    assert "Agent B 结构化摘要" in text
    assert "market_intent = 诱上" in text
    assert "micro_bias = 主队不胜" in text


def test_build_conflict_matrix_hint_flags_structured_conflicts():
    agent_a = """A正文
[A_STRUCTURED]
fundamental_side: 主队优势
motivation_bias: 主队更强
injury_bias: 客队受损
intel_bias: 主队受支持
nspf_tilt: 胜平
[/A_STRUCTURED]"""
    agent_b = """B正文
[B_STRUCTURED]
market_side: 让球方
market_intent: 诱上
intel_support: 情报分裂
micro_bias: 主队不胜
nspf_tilt: 平负
[/B_STRUCTURED]"""
    text = LLMPredictor._build_conflict_matrix_hint(
        agent_a_conclusion=agent_a,
        agent_b_conclusion=agent_b,
        has_anchor_divergence=True,
        triggered_rule_ids=["R205"],
    )

    assert "四维冲突矩阵" in text
    assert "基本面倾向 vs 盘口倾向" in text
    assert "明显冲突" in text
    assert "欧亚存在分工背离" in text
    assert "当前至少存在两处高冲突证据" in text


def test_evaluate_conflict_matrix_returns_high_severity():
    agent_a = """A正文
[A_STRUCTURED]
fundamental_side: 主队优势
motivation_bias: 主队更强
injury_bias: 客队受损
intel_bias: 主队受支持
nspf_tilt: 胜平
[/A_STRUCTURED]"""
    agent_b = """B正文
[B_STRUCTURED]
market_side: 让球方
market_intent: 诱上
intel_support: 情报分裂
micro_bias: 主队不胜
nspf_tilt: 平负
[/B_STRUCTURED]"""
    assessment = LLMPredictor._evaluate_conflict_matrix(
        agent_a_conclusion=agent_a,
        agent_b_conclusion=agent_b,
        has_anchor_divergence=True,
        triggered_rule_ids=["R205"],
    )

    assert assessment["severity"] == "high"
    assert assessment["tilt_relation"] == "明显冲突"
    assert assessment["conflict_flags"] >= 2
    assert any("基本面倾向" in point for point in assessment["conflict_points"])


def test_build_retry_messages_uses_giving_side_not_home_side():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": False,
        "must_double_nspf": False,
        "must_double_rq": False,
        "must_explain_market_anchor": False,
        "confidence_cap": None,
    }
    details = {
        "analysis_panpei": "机构诱上，真实意图是诱导买入让球方。",
        "recommendation_nspf": "负(60%)/平(40%)",
        "recommendation_rq": "让负",
        "confidence": "58",
    }
    match_asian_odds = {
        "macau": {
            "start": "0.92 | 受半球 | 0.78",
            "live": "0.96 | 受半球 | 0.82",
        }
    }

    msgs = predictor._build_retry_messages(
        result_text="盘口解析提到诱上，但没有纠偏。",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds=match_asian_odds,
        triggered_rule_ids=[],
    )

    assert any("客队（让球方）" in msg for msg in msgs)
    assert any("回看基本面摘要" in msg or "重新核验" in msg for msg in msgs)


def test_build_retry_messages_rejects_no_conflict_on_high_conflict_matrix():
    predictor = _make_predictor()
    details = {
        "analysis_panpei": "盘赔微观信号规则匹配：[R205]\n机构诱上，防主队不胜。",
        "analysis_arbitration": "基本面方向：主队小优\n盘赔方向：诱上，防主队不胜\n情报佐证结论：情报分裂\n微观规则结论：[R205] 支持防主胜\n最终仲裁方向：平/负\n推翻原因：无明显冲突，无需推翻",
        "arb_fundamental": "主队小优",
        "arb_market": "诱上，防主队不胜",
        "arb_intel": "情报分裂",
        "arb_micro": "[R205] 支持防主胜",
        "arb_final": "平/负",
        "arb_override_reason": "无明显冲突，无需推翻",
        "recommendation_nspf": "平(55%)/负(45%)",
        "recommendation_rq": "让负(60%)/让平(40%)",
        "confidence": "58",
    }
    conflict_assessment = {
        "severity": "high",
        "tilt_relation": "明显冲突",
        "conflict_flags": 3,
        "conflict_points": [
            "基本面倾向=胜平，盘口倾向=平负，二者结构化方向明显冲突",
            "欧亚锚点存在分工背离，盘口方向与强弱锚点可能错位",
        ],
    }

    msgs = predictor._build_retry_messages(
        result_text="测试文本",
        details=details,
        risk_policy={
            "must_cover_micro_signals": False,
            "must_double_nspf": False,
            "must_double_rq": False,
            "must_explain_market_anchor": False,
            "confidence_cap": None,
        },
        match_asian_odds={"macau": {"start": "0.82 | 半球 | 1.02", "live": "0.96 | 半球/一球 | 0.86"}},
        triggered_rule_ids=["R205"],
        conflict_assessment=conflict_assessment,
    )

    assert any("至少存在两处高冲突证据" in msg for msg in msgs)
    assert any("基本面倾向=胜平" in msg for msg in msgs)


def test_parse_prediction_details_extracts_panpei_section():
    text = """- **【赛事概览与风险分级】**：测试
- **【基本面剖析】**：基本面内容
- **【盘赔深度解析】**：机构判断为诱上，并明确回应 [test_rule]，防住主队过热方向。
- **【核心风控提示】**：最大风险是盘口诱导。
- **🎯 最终预测**：
   - **竞彩推荐**：平(50%)/负(50%)
   - **竞彩让球推荐**：让负(60%)/让平(40%)
   - **竞彩置信度**：60
"""
    details = LLMPredictor.parse_prediction_details(text)

    assert "诱上" in details["analysis_panpei"]
    assert "[test_rule]" in details["analysis_panpei"]
    assert details["confidence"] == "60"


def test_parse_prediction_details_extracts_arbitration_section():
    text = """- **【赛事概览与风险分级】**：测试
- **【基本面剖析】**：基本面内容
- **【盘赔深度解析】**：盘赔微观信号规则匹配：[R205]
机构判断为诱上，并明确回应 [R205]。
- **【四维仲裁】**：
  - 基本面方向：主队小优
  - 盘赔方向：诱上，防主队不胜
  - 情报佐证结论：客队伤停利空真实存在，但不足以完全推翻盘口诱上
  - 微观规则结论：[R205] 支持防主胜
  - 最终仲裁方向：平(55%)/负(45%)
  - 推翻原因：盘赔方向与微观规则共同压制基本面主队小优，最终由盘口层推翻基本面层
- **【核心风控提示】**：最大风险是盘口诱导。
- **🎯 最终预测**：
   - **竞彩推荐**：平(55%)/负(45%)
   - **竞彩让球推荐**：让负(60%)/让平(40%)
   - **竞彩置信度**：58
"""
    details = LLMPredictor.parse_prediction_details(text)

    assert details["analysis_panpei"].startswith("盘赔微观信号规则匹配")
    assert details["arb_fundamental"] == "主队小优"
    assert "诱上" in details["arb_market"]
    assert "[R205]" in details["arb_micro"]
    assert details["arb_final"] == "平(55%)/负(45%)"
    assert "推翻基本面层" in details["arb_override_reason"]


def test_build_retry_messages_requires_double_when_confidence_below_60():
    predictor = _make_predictor()
    risk_policy = {
        "must_cover_micro_signals": False,
        "must_double_nspf": False,
        "must_double_rq": False,
        "must_explain_market_anchor": False,
        "confidence_cap": None,
    }
    details = {
        "analysis_panpei": "盘赔微观信号规则匹配：无盘赔微观信号规则匹配。\n机构诱上，需防主队过热。",
        "analysis_arbitration": "基本面方向：均势偏主\n盘赔方向：诱上\n情报佐证结论：不足以支撑升盘\n微观规则结论：无盘赔微观信号规则匹配\n最终仲裁方向：平/负\n推翻原因：盘口维度推翻基本面维度",
        "arb_fundamental": "均势偏主",
        "arb_market": "诱上",
        "arb_intel": "不足以支撑升盘",
        "arb_micro": "无盘赔微观信号规则匹配",
        "arb_final": "平/负",
        "arb_override_reason": "盘口维度推翻基本面维度",
        "recommendation_nspf": "平(100%)",
        "recommendation_rq": "让负(100%)",
        "confidence": "45",
    }

    msgs = predictor._build_retry_messages(
        result_text="测试文本",
        details=details,
        risk_policy=risk_policy,
        match_asian_odds={"macau": {"start": "0.79 | 半球 | 0.99", "live": "0.96 | 半球/一球 | 0.82"}},
        triggered_rule_ids=[],
    )

    assert any("竞彩置信度低于 60，不让球推荐必须双选" in msg for msg in msgs)
    assert any("竞彩让球推荐必须双选" in msg for msg in msgs)


def test_enforce_minimum_risk_coverage_expands_double_when_confidence_below_60():
    text = """## 【盘赔深度解析】
盘赔微观信号规则匹配：无盘赔微观信号规则匹配。
机构诱上，防主队过热。

## 🎯 最终预测
- **竞彩推荐**：平(100%)
- **竞彩让球推荐**：让负(100%)
- **竞彩置信度**：45
"""
    details = LLMPredictor.parse_prediction_details(text)
    new_text, changed = LLMPredictor._enforce_minimum_risk_coverage(
        text,
        details,
        {
            "must_cover_micro_signals": False,
            "must_double_nspf": False,
            "must_double_rq": False,
            "must_explain_market_anchor": False,
            "confidence_cap": None,
        },
        {"macau": {"start": "0.79 | 半球 | 0.99", "live": "0.96 | 半球/一球 | 0.82"}},
    )

    assert changed is True
    assert "竞彩推荐**：平(55%)/负(45%)" in new_text
    assert "竞彩让球推荐**：让负(55%)/让平(45%)" in new_text


def test_detect_euro_asian_divergence_uses_euro_strength_side():
    odds = {"nspf": ["2.00", "3.20", "2.10"]}
    asian = {"macau": {"start": "0.92 | 半球 | 0.94"}}
    europe_odds = [
        {
            "company": "澳门",
            "init_home": "2.45",
            "init_away": "1.75",
            "live_home": "2.55",
            "live_away": "1.72",
        }
    ]

    warning = LLMPredictor._detect_euro_asian_divergence(odds, asian, europe_odds)

    assert warning
    assert "客队" in warning
    assert "必须防范" not in warning
    assert "大概率能打出" not in warning


def test_detect_shallow_water_trap_uses_giving_side_water():
    asian = {
        "macau": {
            "start": "0.94 | 受平手/半球 | 0.82",
            "live": "0.88 | 受平手/半球 | 1.02",
        }
    }
    odds = {"nspf": ["3.30", "3.10", "2.05"]}

    warning = LLMPredictor._detect_shallow_water_trap(asian, odds)

    assert warning
    assert "让球方（客队）" in warning
    assert "客队不胜" in warning


def test_detect_odds_change_uses_left_right_labels_not_upper_lower():
    asian = {
        "macau": {
            "start": "0.92 | 受半球 | 0.78",
            "live": "0.97 | 受半球 | 0.74",
        }
    }

    summary = LLMPredictor._detect_odds_change(asian)

    assert "左侧水位" in summary
    assert "右侧水位" in summary
    assert "上盘水位" not in summary
    assert "下盘水位" not in summary


def test_detect_odds_change_recognizes_away_upgrade():
    asian = {
        "macau": {
            "start": "0.92 | 受半球 | 0.78",
            "live": "0.97 | 受半球/一球 | 0.74",
        }
    }

    summary = LLMPredictor._detect_odds_change(asian)

    assert "升盘(受半球→受半球/一球)" in summary


def test_league_hints_do_not_hardcode_home_team_bias():
    eng_hint = LLMPredictor._get_league_hint("英冠")
    nordic_hint = LLMPredictor._get_league_hint("挪超")

    assert "主队不败" not in eng_hint
    assert "首选胜/平" not in eng_hint
    assert "主队屠杀" not in nordic_hint
    assert "不要把主场优势直接等同于可轻松打穿" in nordic_hint


def test_half_ball_trap_uses_giving_side_not_strong_team_wording():
    asian = {
        "macau": {
            "start": "0.82 | 半球 | 1.02",
            "live": "0.92 | 半球 | 1.12",
        }
    }

    warning = LLMPredictor._detect_half_ball_trap(asian, odds={})

    assert warning
    assert "让球方" in warning
    assert "强队" not in warning
    assert "上盘胜" not in warning


def test_half_ball_water_drop_no_rise_no_longer_triggers_on_ultra_low_water_control():
    asian = {
        "macau": {
            "start": "0.93 | 半球 | 0.93",
            "live": "0.80 | 半球 | 0.98",
        }
    }
    odds = {"nspf": ["1.64", "3.80", "4.60"]}

    text = LLMPredictor._analyze_micro_market_signals(odds, asian, "瑞超")

    assert "half_ball_water_drop_no_rise" not in text


def test_half_ball_ultra_low_water_support_favorite_triggers_on_control_heat_shape():
    asian = {
        "macau": {
            "start": "0.93 | 半球 | 0.93",
            "live": "0.80 | 半球 | 0.98",
        }
    }
    odds = {"nspf": ["1.64", "3.80", "4.60"]}

    text = LLMPredictor._analyze_micro_market_signals(odds, asian, "瑞超")

    assert "half_ball_ultra_low_water_support_favorite" in text
    assert "主胜方向" in text
    assert "【预测偏向：胜】" in text


def test_deep_handicap_rise_with_water_rise_triggers_new_micro_signal():
    asian = {
        "macau": {
            "start": "0.77 | 一球/球半 | 1.01",
            "live": "1.00 | 球半 | 0.78",
        }
    }
    odds = {"nspf": ["1.55", "4.05", "4.80"]}

    text = LLMPredictor._analyze_micro_market_signals(odds, asian, "德乙")

    assert "deep_handicap_rise_with_water_rise" in text
    assert "让球方赢球输盘" in text


def test_pk025_drop_to_pk_low_water_guard_triggers_for_home_protection_shape():
    predictor = _make_predictor()
    result = predictor._evaluate_arbitration_rules(
        {
            "informative_dimension_count": 3,
            "market_micro_aligned": False,
            "reverse_only_from_fundamental_or_intel": False,
            "asian": {"start_hv": 0.25, "live_hv": 0.0, "giving_live_w": 0.78},
        }
    )

    assert result["override_blocked"] is True
    assert any("平半退平手且上盘终盘超低水" in msg for msg in result["guard_messages"])


def test_deep_water_trap_uses_upset_direction_by_giving_side():
    asian = {
        "macau": {
            "start": "1.02 | 受两球 | 0.80",
            "live": "1.01 | 受两球 | 0.81",
        }
    }

    warning = LLMPredictor._detect_deep_water_trap(asian)

    assert warning
    assert "胜/平" in warning
    assert "客胜爆大冷" not in warning


def test_handicap_water_divergence_does_not_hardcode_ping_fu():
    asian = {
        "macau": {
            "start": "0.86 | 受半球 | 0.92",
            "live": "0.88 | 受半球/一球 | 1.00",
        }
    }

    warning = LLMPredictor._detect_handicap_water_divergence(asian)

    assert warning
    assert "受让方方向风险" in warning
    assert "推平/负" not in warning


def test_build_agent_c_guardrails_are_conditional():
    predictor = _make_predictor()

    guardrails = predictor._build_agent_c_guardrails(
        dynamic_rules="### 🟡 B. 浅盘 (平半~半球) 专属规则\n- 浅盘示弱总则",
        leisu_brief="- 结构化伤停：主队伤病2人",
        formatted_data="- 🔎 市场锚点定义：亚赔实际让球方/上盘 = 主队；欧赔实力方 = 客队。",
    )

    assert "去重执行口径" in guardrails
    assert "结构化伤停引用硬约束" in guardrails
    assert "欧亚锚点硬约束" in guardrails


def test_build_agent_c_guardrails_skip_irrelevant_sections():
    predictor = _make_predictor()

    guardrails = predictor._build_agent_c_guardrails(
        dynamic_rules="### 🟡 C. 中盘 (半一~一球) 专属规则\n- 升盘+升水背离",
        leisu_brief="无",
        formatted_data="普通比赛原始数据",
    )

    assert "去重执行口径" not in guardrails
    assert "结构化伤停引用硬约束" not in guardrails
    assert "欧亚锚点硬约束" not in guardrails


def test_enforce_minimum_risk_coverage_restores_double_nspf():
    predictor = _make_predictor()
    risk_policy = {
        "must_double_nspf": True,
        "must_double_rq": False,
    }
    details = {
        "analysis_panpei": "机构阻上，真实防范让球方。",
        "recommendation_nspf": "胜",
        "recommendation_rq": "让平(60%)/让胜(40%)",
    }
    text = """- **🎯 最终预测**：
   - **竞彩推荐**：[胜]
   - **竞彩让球推荐**：[让平(60%)/让胜(40%)]
"""
    asian = {"macau": {"start": "0.86 | 半球 | 0.96", "live": "0.82 | 半球 | 1.02"}}

    new_text, changed = predictor._enforce_minimum_risk_coverage(text, details, risk_policy, asian)

    assert changed is True
    assert "竞彩推荐**：胜(55%)/平(45%)" in new_text


def test_determine_prediction_period_accepts_second_precision_match_time():
    predictor = _make_predictor()
    future_match_time = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

    period = predictor._determine_prediction_period({"match_time": future_match_time})

    assert period == "pre_24h"


def test_enforce_minimum_risk_coverage_restores_double_rq():
    predictor = _make_predictor()
    risk_policy = {
        "must_double_nspf": False,
        "must_double_rq": True,
    }
    details = {
        "analysis_panpei": "机构诱上，诱导买入让球方。",
        "recommendation_nspf": "平(55%)/负(45%)",
        "recommendation_rq": "让负",
    }
    text = """- **🎯 最终预测**：
   - **竞彩推荐**：[平(55%)/负(45%)]
   - **竞彩让球推荐**：[让负]
"""
    asian = {"macau": {"start": "0.86 | 半球 | 0.96", "live": "0.90 | 半球 | 0.98"}}

    new_text, changed = predictor._enforce_minimum_risk_coverage(text, details, risk_policy, asian)

    assert changed is True
    assert "竞彩让球推荐**：让负(55%)/让平(45%)" in new_text


def test_enforce_minimum_risk_coverage_does_not_force_realign_existing_double_pick():
    predictor = _make_predictor()
    risk_policy = {
        "must_double_nspf": True,
        "must_double_rq": False,
    }
    details = {
        "analysis_panpei": "机构诱上，诱导买入让球方。",
        "recommendation_nspf": "平(55%)/胜(45%)",
        "recommendation_rq": "让负",
    }
    text = """- **🎯 最终预测**：
   - **竞彩推荐**：[平(55%)/胜(45%)]
   - **竞彩让球推荐**：[让负]
"""
    asian = {"macau": {"start": "0.86 | 半球 | 0.96", "live": "0.90 | 半球 | 0.98"}}

    new_text, changed = predictor._enforce_minimum_risk_coverage(text, details, risk_policy, asian)

    assert changed is False
    assert new_text == text


def _sample_parlay_summary(match_num, confidence, nspf="胜", rq="让胜", reason="主队状态与盘口一致", goals="2,3球", nspf_odds=None, rq_odds=None):
    return {
        "编号": match_num,
        "赛事": "英超",
        "主队": f"主队{match_num}",
        "客队": f"客队{match_num}",
        "开赛时间": "2026-05-09 19:35",
        "竞彩推荐": nspf,
        "竞彩推荐(不让球)": nspf,
        "竞彩让球推荐": rq,
        "不让球赔率(胜/平/负)": nspf_odds or ["1.72", "3.30", "4.40"],
        "让球赔率(胜/平/负)": rq_odds or ["2.85", "3.15", "2.08"],
        "让球数": "-1",
        "胜平负置信度": str(confidence),
        "置信度": str(confidence),
        "比分参考": "2-1",
        "AI预测进球数": goals,
        "基础理由": reason,
    }


def test_build_parlay_candidates_generates_scored_entries():
    predictor = _make_predictor()
    candidates = predictor._build_parlay_candidates([
        _sample_parlay_summary("周五001", 74)
    ])

    assert len(candidates) == 1
    assert candidates[0]["match_id"] == "周五001"
    assert candidates[0]["scores"]["stable"] >= 0
    assert candidates[0]["primary_play"]["market"] in {"nspf", "rq"}
    assert "稳胆候选" in candidates[0]["tags"]
    assert candidates[0]["tier"] == "stable"


def test_compose_three_parlay_plans_returns_fixed_templates():
    predictor = _make_predictor()
    plans = predictor._compose_three_parlay_plans(
        predictor._build_parlay_candidates([
            _sample_parlay_summary("周五001", 76, reason="稳胆一号"),
            _sample_parlay_summary("周五002", 72, reason="稳胆二号"),
            _sample_parlay_summary("周五003", 66, nspf="平/负", rq="让负", reason="具备赔率价值"),
            _sample_parlay_summary("周五004", 62, nspf="平", rq="让负", reason="存在独立冷门逻辑", nspf_odds=["2.95", "3.05", "2.42"]),
        ])
    )

    assert [plan["plan_code"] for plan in plans] == ["A", "B", "C"]
    assert all(len(plan["matches"]) == 2 for plan in plans)


def test_compose_three_parlay_plans_limits_match_reuse_to_two_times():
    predictor = _make_predictor()
    plans = predictor._compose_three_parlay_plans(
        predictor._build_parlay_candidates([
            _sample_parlay_summary("周五001", 78, reason="全场最稳"),
            _sample_parlay_summary("周五002", 73, reason="第二稳胆"),
            _sample_parlay_summary("周五003", 65, nspf="平/负", rq="让负", reason="平衡价值"),
            _sample_parlay_summary("周五004", 61, nspf="平", rq="让负", reason="高赔博胆", nspf_odds=["3.40", "3.05", "2.05"]),
        ])
    )

    appearances = {}
    for plan in plans:
        for match in plan["matches"]:
            appearances[match["match_id"]] = appearances.get(match["match_id"], 0) + 1

    assert max(appearances.values()) <= 2


def test_compose_three_parlay_plans_targets_expected_payout_ranges():
    predictor = _make_predictor()
    plans = predictor._compose_three_parlay_plans(
        predictor._build_parlay_candidates([
            _sample_parlay_summary("周五001", 78, nspf="胜", reason="头号稳胆", nspf_odds=["1.72", "3.30", "4.40"]),
            _sample_parlay_summary("周五002", 74, nspf="胜", reason="二号稳胆", nspf_odds=["1.82", "3.20", "4.10"]),
            _sample_parlay_summary("周五003", 68, nspf="负", rq="让负", reason="客胜赔率价值明显", nspf_odds=["3.10", "3.20", "3.40"]),
            _sample_parlay_summary("周五004", 64, nspf="负", rq="让负", reason="高赔冷门逻辑成立", nspf_odds=["3.60", "3.30", "4.80"]),
            _sample_parlay_summary("周五005", 66, nspf="平", rq="让负", reason="平局阻上具备爆点", nspf_odds=["2.70", "3.45", "2.55"]),
        ])
    )

    payout_a = predictor._calc_plan_payout(plans[0])
    payout_b = predictor._calc_plan_payout(plans[1])
    payout_c = predictor._calc_plan_payout(plans[2])

    assert 2.5 <= payout_a["net_min"] <= 5.0 or 2.5 <= payout_a["net_max"] <= 5.0
    assert payout_b["net_max"] >= 5.0
    assert payout_c["net_max"] >= 5.0
    assert "目标" in plans[0]["target_status"]


def test_generate_parlays_outputs_three_fixed_sections():
    predictor = _make_predictor()
    text = predictor.generate_parlays([
        _sample_parlay_summary("周五001", 76, reason="稳胆一号"),
        _sample_parlay_summary("周五002", 72, reason="稳胆二号"),
        _sample_parlay_summary("周五003", 66, nspf="平/负", rq="让负", reason="具备赔率价值"),
        _sample_parlay_summary("周五004", 62, nspf="平", rq="让负", reason="存在独立冷门逻辑", nspf_odds=["2.95", "3.05", "2.42"]),
    ])

    assert "### 方案A：主推稳健单" in text
    assert "### 方案B：平衡增益单" in text
    assert "### 方案C：利润冲击单" in text
    assert "注数计算:" in text
    assert "真实净回报：" in text
    assert "赔率目标" in text


def test_generate_parlays_payload_returns_structured_cards():
    predictor = _make_predictor()
    payload = predictor.generate_parlays_payload([
        _sample_parlay_summary("周五001", 76, reason="稳胆一号"),
        _sample_parlay_summary("周五002", 72, reason="稳胆二号"),
        _sample_parlay_summary("周五003", 66, nspf="平/负", rq="让负", reason="具备赔率价值"),
        _sample_parlay_summary("周五004", 62, nspf="平", rq="让负", reason="存在独立冷门逻辑", nspf_odds=["2.95", "3.05", "2.42"]),
    ])

    assert "markdown" in payload
    assert len(payload["plans"]) == 3
    assert payload["plans"][0]["plan_code"] == "A"
    assert "target_status" in payload["plans"][0]
    assert "payout" in payload["plans"][0]
    assert len(payload["plans"][0]["matches"]) >= 1


def test_generate_parlays_prefers_ai_goals_when_present():
    predictor = _make_predictor()
    text = predictor.generate_parlays([
        _sample_parlay_summary("周五001", 75, goals="3,4球"),
        _sample_parlay_summary("周五002", 71, goals="2,3球"),
        _sample_parlay_summary("周五003", 65, nspf="平/负", rq="让负", reason="具备赔率价值"),
        _sample_parlay_summary("周五004", 62, nspf="平", rq="让负", reason="存在独立冷门逻辑"),
    ])

    assert "进球数参考：3,4球" in text


def test_generate_parlays_includes_risk_notes_and_alternative():
    predictor = _make_predictor()
    text = predictor.generate_parlays([
        _sample_parlay_summary("周五001", 76, reason="稳胆一号"),
        _sample_parlay_summary("周五002", 72, reason="稳胆二号"),
        _sample_parlay_summary("周五003", 67, nspf="平/负", rq="让负", reason="具备赔率价值"),
        _sample_parlay_summary("周五004", 63, nspf="平", rq="让负", reason="存在独立冷门逻辑", nspf_odds=["2.95", "3.05", "2.42"]),
        _sample_parlay_summary("周五005", 66, nspf="负", rq="让负", reason="受让与赔率错配支撑", nspf_odds=["3.60", "3.15", "2.02"]),
    ])

    assert "入选理由：" in text
    assert "风险提示：" in text
    assert "备选替换场" in text


def test_calc_plan_payout_uses_note_count_formula():
    predictor = _make_predictor()
    plan = {
        "plan_code": "X",
        "plan_name": "测试方案",
        "matches": [
            {
                "match_id": "周五001",
                "primary_play": {
                    "selection": "胜",
                    "min_odds": 1.72,
                    "max_odds": 1.72,
                    "options_count": 1,
                    "odds": [1.72],
                },
            },
            {
                "match_id": "周五002",
                "primary_play": {
                    "selection": "平/负",
                    "min_odds": 3.30,
                    "max_odds": 4.40,
                    "options_count": 2,
                    "odds": [3.30, 4.40],
                },
            },
        ],
    }

    payout = predictor._calc_plan_payout(plan)

    assert payout["notes_count"] == 2
    assert round(payout["min_product"], 2) == 5.68
    assert round(payout["max_product"], 2) == 7.57
    assert round(payout["net_min"], 2) == 2.84
    assert round(payout["net_max"], 2) == 3.78


def test_build_primary_play_can_fallback_to_estimated_goals():
    predictor = _make_predictor()
    play = predictor._build_primary_play({
        "竞彩推荐(不让球)": "无",
        "竞彩推荐": "无",
        "竞彩让球推荐": "无",
        "不让球赔率(胜/平/负)": [],
        "让球赔率(胜/平/负)": [],
        "AI预测进球数": "2,3球",
        "置信度": "66",
        "胜平负置信度": "66",
        "让球数": "0",
    })

    assert play["market"] == "goals"
    assert play["estimated"] is True
    assert play["options_count"] == 2


def test_generate_parlays_marks_estimated_sp_for_goals_fallback():
    predictor = _make_predictor()
    text = predictor.generate_parlays([
        _sample_parlay_summary("周五001", 76, reason="稳胆一号"),
        {
            "编号": "周五002",
            "赛事": "英超",
            "主队": "主队周五002",
            "客队": "客队周五002",
            "开赛时间": "2026-05-09 19:35",
            "竞彩推荐": "无",
            "竞彩推荐(不让球)": "无",
            "竞彩让球推荐": "无",
            "不让球赔率(胜/平/负)": [],
            "让球赔率(胜/平/负)": [],
            "让球数": "0",
            "胜平负置信度": "66",
            "置信度": "66",
            "比分参考": "2-1",
            "AI预测进球数": "2,3球",
            "基础理由": "进球分布与节奏支持2,3球区间",
        },
    ])

    assert "(估算SP)" in text
