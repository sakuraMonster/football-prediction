import json
import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

from src.utils.rule_drafts import (
    append_rule_drafts,
    delete_rule_draft,
    get_pending_rule_drafts,
    load_rule_drafts,
    save_rule_drafts,
    update_rule_draft_status,
)
from src.utils.rule_registry import (
    convert_draft_to_arbitration_rule,
    convert_draft_to_micro_rule,
    ensure_unique_rule_id,
    generate_rule_id_from_draft,
    get_micro_rules_path,
    load_rule_list,
    normalize_micro_rule_condition,
    normalize_arbitration_rule_action,
)
from src.llm.predictor import LLMPredictor
from scripts.run_post_mortem import _build_market_replay_summary


def test_rule_files_exist_with_expected_top_level_shape():
    base = Path(r"e:\zhangxuejun\football-prediction\data\rules")
    micro = json.loads((base / "micro_signals.json").read_text(encoding="utf-8"))
    arbitration = json.loads((base / "arbitration_rules.json").read_text(encoding="utf-8"))
    drafts = json.loads((base / "rule_drafts.json").read_text(encoding="utf-8"))

    assert isinstance(micro, list)
    assert isinstance(arbitration, list)
    assert isinstance(drafts, list)


def test_save_rule_drafts_persists_new_items():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rule_drafts.json"
        save_rule_drafts(path, [{"draft_id": "draft_001", "status": "draft"}])

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["draft_id"] == "draft_001"


def test_append_rule_drafts_deduplicates_by_draft_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rule_drafts.json"
        save_rule_drafts(path, [{"draft_id": "draft_001", "status": "accepted"}])
        append_rule_drafts(
            path,
            [
                {"draft_id": "draft_001", "status": "draft"},
                {"draft_id": "draft_002", "status": "draft"},
            ],
        )

        data = load_rule_drafts(path)
        assert len(data) == 2
        assert [item["draft_id"] for item in data] == ["draft_001", "draft_002"]


def test_convert_draft_to_arbitration_rule():
    draft = {
        "title": "信息真空禁止预测",
        "target_scope": "arbitration_guard",
        "suggested_condition": "ctx['informative_dimension_count'] < 2",
        "suggested_action": "abort_prediction",
        "problem_type": "信息真空",
    }

    rule = convert_draft_to_arbitration_rule(draft)
    assert rule["category"] == "arbitration_guard"
    assert rule["action_type"] == "abort_prediction"
    assert rule["condition"] == "ctx['informative_dimension_count'] < 2"


def test_convert_draft_to_arbitration_rule_rewrites_asian_condition_to_ctx_scope():
    draft = {
        "title": "平半退平手低水保护",
        "target_scope": "arbitration_guard",
        "suggested_condition": "asian['start_hv'] == 0.25 and asian['live_hv'] == 0.0 and asian['giving_live_w'] <= 0.80",
        "suggested_action": "在四维仲裁时，触发风控铁律修正案：此盘口模式属于‘正路保护’，而非‘诱上后控热’。若基本面无明确反对，应优先考虑主队不败甚至主胜方向。",
    }

    rule = convert_draft_to_arbitration_rule(draft)
    assert rule["condition"] == "ctx['asian'].get('start_hv') == 0.25 and ctx['asian'].get('live_hv') == 0.0 and ctx['asian'].get('giving_live_w') <= 0.80"
    assert rule["action_type"] == "forbid_override"


def test_normalize_arbitration_rule_action_maps_abort_text_to_abort_prediction():
    action_type, payload = normalize_arbitration_rule_action(
        "触发熔断机制，将最终预测强制设为无法预测，并附加建议规避提示"
    )

    assert action_type == "abort_prediction"
    assert "无法预测" in payload["message"]


def test_convert_draft_to_micro_rule():
    draft = {
        "title": "升盘升水阻上识别",
        "target_scope": "micro_signal",
        "suggested_condition": "asian['live_hv'] > asian['start_hv']",
        "suggested_action": "bias_to_giving_side",
        "suggested_bias": "胜",
        "trigger_condition_nl": "升盘升水时看强势方",
        "problem_type": "阻上误判",
    }

    rule = convert_draft_to_micro_rule(draft)
    assert rule["category"] == "micro_signal"
    assert rule["prediction_bias"] == "胜"
    assert "升盘升水时看强势方" in rule["warning_template"]


def test_convert_draft_to_micro_rule_prefers_formal_fields():
    draft = {
        "title": "旧标题",
        "rule_name": "正式微观规则名",
        "target_scope": "micro_signal",
        "suggested_condition": "asian['live_hv'] > asian['start_hv']",
        "suggested_action": "old_action",
        "suggested_bias": "平负",
        "warning_message_template": "正式警告模板",
        "prediction_bias": "胜平",
        "effect_type": "提高让球方评级",
        "scenario_key": "平手盘_原盘_升水",
        "scenario_parts": ["平手盘", "原盘", "升水"],
        "scenario_version": "v1",
    }

    rule = convert_draft_to_micro_rule(draft)
    assert rule["name"] == "正式微观规则名"
    assert rule["warning_template"] == "正式警告模板"
    assert rule["prediction_bias"] == "胜平"
    assert rule["effect"] == "提高让球方评级"
    assert rule["scenario_key"] == "平手盘_原盘_升水"
    assert rule["scenario_parts"] == ["平手盘", "原盘", "升水"]
    assert rule["scenario_version"] == "v1"


def test_convert_draft_to_micro_rule_prefers_actual_result_bias():
    draft = {
        "title": "旧标题",
        "rule_name": "正式微观规则名",
        "target_scope": "micro_signal",
        "suggested_condition": "asian['live_hv'] > asian['start_hv']",
        "suggested_bias": "平负",
        "prediction_bias": "平负",
        "actual_nspf": "胜",
        "warning_message_template": "正式警告模板",
        "effect_type": "提高让球方评级",
    }

    rule = convert_draft_to_micro_rule(draft)
    assert rule["prediction_bias"] == "胜"


def test_enforce_error_case_coverage_prefers_actual_result_for_normalized_draft_bias():
    errors = [
        {
            "match_num": "周六009",
            "home": "萨普斯堡",
            "away": "腓特烈",
            "asian_start": "0.980 | 半球 | 0.800",
            "asian_live": "0.800↓ | 半球 | 0.980↑",
            "market_replay_summary": "半球盘-原盘-降水-主强中度优势-欧赔客胜上调剧烈",
            "actual_nspf": "胜",
            "actual_score": "2:1",
        }
    ]
    rule_drafts = [
        {
            "case_id": "周六009|萨普斯堡 vs 腓特烈",
            "draft_id": "DRAFT-TEST-001",
            "title": "半球盘-原盘-降水-主强中度优势-欧赔客胜上调剧烈-微观规则",
            "target_scope": "micro_signal",
            "suggested_condition": "asian['start_hv'] == 0.5",
            "suggested_bias": "平负",
            "prediction_bias": "平负",
            "warning_message_template": "旧模板，再次出现该形态时，直接触发预警，优先按平负方向防范",
            "effect_type": "提高让球方评级",
            "status": "draft",
        }
    ]

    _, normalized_drafts = LLMPredictor._enforce_error_case_coverage(
        errors=errors,
        case_mappings=[],
        rule_drafts=rule_drafts,
        report_date="2026-05-09",
    )

    draft = normalized_drafts[0]
    assert draft["actual_nspf"] == "胜"
    assert draft["suggested_bias"] == "胜"
    assert draft["prediction_bias"] == "胜"
    assert "程序化标准偏向：胜" in draft["warning_message_template"]
    assert "基本面" not in draft["warning_message_template"]
    assert "情报" not in draft["warning_message_template"]
    assert "错因：" not in draft["warning_message_template"]


def test_enforce_error_case_coverage_rebuilds_dirty_warning_template_from_scenario():
    errors = [
        {
            "match_num": "周六002",
            "home": "大阪樱花",
            "away": "长崎航海",
            "asian_start": "0.870 | 半球 | 0.970",
            "asian_live": "0.880↑ | 半球/一球 升 | 0.960↓",
            "market_replay_summary": "半球盘-水位平稳-主强强弱分明-欧赔客胜上调剧烈",
            "actual_nspf": "胜",
            "actual_score": "3:2",
        }
    ]
    rule_drafts = [
        {
            "case_id": "周六002|大阪樱花 vs 长崎航海",
            "draft_id": "DRAFT-TEST-DIRTY",
            "title": "半球盘-水位平稳-主强强弱分明-欧赔客胜上调剧烈-微观规则",
            "target_scope": "micro_signal",
            "suggested_condition": "asian['start_hv'] == 0.5",
            "suggested_bias": "胜",
            "prediction_bias": "胜",
            "warning_message_template": "错因：基本面利好主队；情报也支持主队；以下维度信息不足或未形成明确方向：基本面、盘赔、情报、微观规则。",
            "effect_type": "补充新规则",
            "status": "draft",
        }
    ]

    _, normalized_drafts = LLMPredictor._enforce_error_case_coverage(
        errors=errors,
        case_mappings=[],
        rule_drafts=rule_drafts,
        report_date="2026-05-09",
    )

    draft = normalized_drafts[0]
    assert "程序化标准偏向：胜" in draft["warning_message_template"]
    assert "命中盘口剧本：" in draft["warning_message_template"]
    assert "基本面" not in draft["warning_message_template"]
    assert "情报" not in draft["warning_message_template"]
    assert "以下维度信息不足或未形成明确方向" not in draft["warning_message_template"]


def test_enforce_error_case_coverage_always_generates_micro_signal_drafts():
    errors = [
        {
            "match_num": "周六011",
            "home": "卡利亚里",
            "away": "乌迪内斯",
            "asian_start": "0.920 | 平手 | 0.960",
            "asian_live": "0.880↓ | 平手 | 1.000↑",
            "market_replay_summary": "平手盘-原盘-降水-主强中度优势-欧赔不跟随",
            "actual_nspf": "胜",
            "actual_score": "1:0",
        }
    ]
    case_mappings = [
        {
            "case_id": "周六011|卡利亚里 vs 乌迪内斯",
            "recommended_target_scope": "arbitration_guard",
        }
    ]
    rule_drafts = [
        {
            "case_id": "周六011|卡利亚里 vs 乌迪内斯",
            "draft_id": "DRAFT-TEST-002",
            "title": "旧仲裁草稿",
            "target_scope": "arbitration_guard",
            "suggested_condition": "ctx['informative_dimension_count'] < 2",
            "action_type": "abort_prediction",
            "action_payload": {"message": "信息不足"},
            "explanation_template": "旧仲裁解释",
            "status": "draft",
        }
    ]

    mappings, normalized_drafts = LLMPredictor._enforce_error_case_coverage(
        errors=errors,
        case_mappings=case_mappings,
        rule_drafts=rule_drafts,
        report_date="2026-05-09",
    )

    assert mappings[0]["recommended_target_scope"] == "micro_signal"
    assert normalized_drafts[0]["target_scope"] == "micro_signal"
    assert normalized_drafts[0]["rule_id"].startswith("micro_rule")


def test_enforce_minimum_risk_coverage_uses_micro_signal_bias_as_prediction_standard():
    prediction_text = "竞彩推荐：胜(60%)\n竞彩让球推荐：让胜(55%)/让平(45%)"
    details = {
        "analysis_panpei": "已命中微观信号",
        "recommendation_nspf": "胜",
        "recommendation_rq": "让胜/让平",
        "confidence": "62%",
    }
    risk_policy = {
        "must_double_nspf": True,
        "must_double_rq": False,
        "micro_signal_bias_standard": "平负",
    }
    asian = {"macau": {"start": "0.92 | 半球 | 0.94", "live": "0.98↑ | 半球 | 0.86↓"}}

    updated_text, changed = LLMPredictor._enforce_minimum_risk_coverage(
        prediction_text,
        details,
        risk_policy,
        asian,
    )

    assert changed is True
    assert "竞彩推荐：平(55%)/负(45%)" in updated_text


def test_scenario_rules_warning_templates_are_clean_and_aligned_with_prediction_bias():
    rules = load_rule_list(get_micro_rules_path())
    scenario_rules = [rule for rule in rules if rule.get("scenario_key")]

    assert scenario_rules
    for rule in scenario_rules:
        warning_template = str(rule.get("warning_template") or "")
        prediction_bias = str(rule.get("prediction_bias") or "")
        assert "程序化标准偏向" in warning_template
        assert prediction_bias in warning_template
        assert "本来更接近赛果的维度" not in warning_template
        assert "推翻原因写成" not in warning_template
        assert "以下维度信息不足或未形成明确方向" not in warning_template


def test_scenario_rules_conditions_use_euro_profile_labels_instead_of_exact_odds_points():
    rules = load_rule_list(get_micro_rules_path())
    scenario_rules = [rule for rule in rules if rule.get("scenario_key")]

    assert scenario_rules
    for rule in scenario_rules:
        condition = str(rule.get("condition") or "")
        assert "euro['macau_start']" not in condition
        assert "euro['bet365_start']" not in condition
        assert "euro['live_home']" not in condition
        assert "euro['live_away']" not in condition
        assert "euro['favored_side']" in condition
        assert "euro['strength_gap_label']" in condition
        assert "euro['movement_side']" in condition
        assert "euro['movement_direction']" in condition
        assert "euro['movement_magnitude']" in condition


def test_build_micro_rule_euro_context_includes_structured_profile_labels():
    europe_odds = [
        {
            "company": "澳门",
            "init_home": "1.98",
            "init_draw": "3.73",
            "init_away": "2.85",
            "live_home": "1.80",
            "live_draw": "3.73",
            "live_away": "3.33",
        }
    ]

    euro = LLMPredictor._build_micro_rule_euro_context(europe_odds)

    assert euro["favored_side"] == "home"
    assert euro["strength_gap_label"] == "中度优势"
    assert euro["movement_side"] == "away"
    assert euro["movement_direction"] == "up"
    assert euro["movement_magnitude"] == "剧烈"


def test_infer_rule_from_market_chain_uses_euro_profile_labels_instead_of_exact_odds_ratios():
    case_match = {
        "asian_start": "0.980 | 半球 | 0.800",
        "asian_live": "0.800↓ | 半球 | 0.980↑",
        "europe_odds": [
            {
                "company": "澳门",
                "init_home": "1.98",
                "init_draw": "3.73",
                "init_away": "2.85",
                "live_home": "1.80",
                "live_draw": "3.73",
                "live_away": "3.33",
            }
        ],
    }

    inferred = LLMPredictor._infer_rule_from_market_chain(
        "周六009 萨普斯堡 vs 腓特烈 | 初盘0.980 | 半球 | 0.800 -> 即时0.800↓ | 半球 | 0.980↑",
        target_scope="micro_signal",
        has_rule_hit=False,
        rule_id="",
        bias_hint="胜",
        case_match=case_match,
    )

    condition = inferred["suggested_condition"]
    assert "euro['favored_side'] == 'home'" in condition
    assert "euro['strength_gap_label'] == '中度优势'" in condition
    assert "euro['movement_side'] == 'away'" in condition
    assert "euro['movement_direction'] == 'up'" in condition
    assert "euro['movement_magnitude'] == '剧烈'" in condition
    assert "1.439" not in condition
    assert "0.168" not in condition
    assert "euro['macau_start']['a'] / euro['macau_start']['h']" not in condition


def test_analyze_micro_market_signals_supports_euro_profile_label_rules():
    rules = [
        {
            "id": "test_micro_label_rule",
            "name": "测试标签规则",
            "level": "🔴高危",
            "enabled": True,
            "condition": (
                "asian['start_hv'] == 0.5 and "
                "euro['favored_side'] == 'home' and "
                "euro['strength_gap_label'] == '中度优势' and "
                "euro['movement_side'] == 'away' and "
                "euro['movement_direction'] == 'up' and "
                "euro['movement_magnitude'] == '剧烈'"
            ),
            "warning_template": "测试剧本命中",
            "prediction_bias": "胜",
        }
    ]
    europe_odds = [
        {
            "company": "澳门",
            "init_home": "1.98",
            "init_draw": "3.73",
            "init_away": "2.85",
            "live_home": "1.80",
            "live_draw": "3.73",
            "live_away": "3.33",
        }
    ]
    asian = {
        "macau": {
            "start": "0.980 | 半球 | 0.800",
            "live": "0.800↓ | 半球 | 0.980↑",
        }
    }

    with patch("src.llm.predictor.os.path.exists", return_value=True), patch(
        "builtins.open",
        mock_open(read_data=json.dumps(rules, ensure_ascii=False)),
    ):
        text = LLMPredictor._analyze_micro_market_signals({}, asian, "", euro_odds=europe_odds)

    assert "test_micro_label_rule" in text
    assert "测试标签规则" in text
    assert "预测偏向：胜" in text


def test_convert_draft_to_arbitration_rule_prefers_formal_fields():
    draft = {
        "title": "旧仲裁标题",
        "rule_name": "正式仲裁规则名",
        "target_scope": "arbitration_guard",
        "suggested_condition": "ctx['informative_dimension_count'] < 2",
        "suggested_action": "old_action",
        "action_type": "abort_prediction",
        "action_payload": {"message": "信息不足，建议回避"},
        "explanation_template": "正式解释模板",
        "priority": 90,
        "scenario_key": "半球盘_原盘_升水",
        "scenario_parts": ["半球盘", "原盘", "升水"],
        "scenario_version": "v1",
    }

    rule = convert_draft_to_arbitration_rule(draft)
    assert rule["name"] == "正式仲裁规则名"
    assert rule["action_type"] == "abort_prediction"
    assert rule["action_payload"]["message"] == "信息不足，建议回避"
    assert rule["explanation_template"] == "正式解释模板"
    assert rule["priority"] == 90
    assert rule["scenario_key"] == "半球盘_原盘_升水"
    assert rule["scenario_parts"] == ["半球盘", "原盘", "升水"]
    assert rule["scenario_version"] == "v1"


def test_market_replay_summary_prefers_asian_and_euro_changes():
    summary = _build_market_replay_summary(
        "0.92 | 半球 | 0.94",
        "1.02↑ | 半球 | 0.82↓",
        [
            {"company": "澳门", "init_home": "2.10", "init_draw": "3.20", "init_away": "3.40", "live_home": "2.24", "live_draw": "3.15", "live_away": "3.18"},
            {"company": "Bet365", "init_home": "2.08", "init_draw": "3.25", "init_away": "3.45", "live_home": "2.18", "live_draw": "3.18", "live_away": "3.22"},
        ],
    )
    assert "半球盘" in summary
    assert "初赔强弱" in summary
    assert "调幅档位=" in summary
    assert "亚盘：初0.92 | 半球 | 0.94 -> 即1.02↑ | 半球 | 0.82↓" in summary
    assert "澳门欧赔" in summary
    assert "主胜上调" in summary or "客胜下调" in summary


def test_predictor_market_rule_name_comes_from_market_shape():
    rule_name = LLMPredictor._build_market_rule_name(
        {
            "asian_start": "0.92 | 半球 | 0.94",
            "asian_live": "1.02↑ | 半球 | 0.82↓",
            "europe_odds": [
                {"company": "澳门", "init_home": "2.10", "init_draw": "3.20", "init_away": "3.40", "live_home": "2.24", "live_draw": "3.15", "live_away": "3.18"},
            ],
        },
        target_scope="micro_signal",
    )
    assert "半球盘" in rule_name
    assert "-" in rule_name
    assert "主强" in rule_name or "客强" in rule_name or "均势" in rule_name
    assert "升水" in rule_name or "原盘" in rule_name or "退盘" in rule_name or "升盘" in rule_name
    assert "轻微" in rule_name or "中等" in rule_name or "剧烈" in rule_name or "不跟随" in rule_name
    assert "欧赔" in rule_name
    assert "微观规则" in rule_name


def test_get_pending_rule_drafts_filters_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rule_drafts.json"
        save_rule_drafts(
            path,
            [
                {"draft_id": "draft_001", "status": "draft"},
                {"draft_id": "draft_002", "status": "accepted"},
            ],
        )
        pending = get_pending_rule_drafts(path)
        assert [item["draft_id"] for item in pending] == ["draft_001"]


def test_update_rule_draft_status_changes_existing_draft():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rule_drafts.json"
        save_rule_drafts(path, [{"draft_id": "draft_001", "status": "draft"}])
        changed = update_rule_draft_status("draft_001", "accepted", path)
        data = load_rule_drafts(path)

        assert changed is True
        assert data[0]["status"] == "accepted"


def test_delete_rule_draft_removes_existing_item():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rule_drafts.json"
        save_rule_drafts(
            path,
            [
                {"draft_id": "draft_001", "status": "draft"},
                {"draft_id": "draft_002", "status": "draft"},
            ],
        )

        changed = delete_rule_draft("draft_001", path)
        data = load_rule_drafts(path)

        assert changed is True
        assert [item["draft_id"] for item in data] == ["draft_002"]


def test_generate_rule_id_from_draft_falls_back_to_prefixed_draft_id_for_chinese_title():
    draft = {
        "draft_id": "DRAFT-003",
        "title": "基本面与盘赔冲突时的优先级修正预警",
        "target_scope": "arbitration_guard",
    }

    rule_id = generate_rule_id_from_draft(draft, category="arbitration_guard")
    assert rule_id == "arbitration_rule_draft_003"


def test_generate_rule_id_from_draft_avoids_existing_ids():
    draft = {
        "draft_id": "DRAFT-001",
        "title": "深盘升盘升水预警：警惕让球方穿盘能力",
        "target_scope": "micro_signal",
    }

    rule_id = generate_rule_id_from_draft(
        draft,
        category="micro_signal",
        existing_ids={"micro_rule_draft_001"},
    )
    assert rule_id == "micro_rule_draft_001_2"


def test_ensure_unique_rule_id_appends_numeric_suffix():
    rule_id = ensure_unique_rule_id("micro_rule_draft_001", {"micro_rule_draft_001", "micro_rule_draft_001_2"})
    assert rule_id == "micro_rule_draft_001_3"


def test_home_odds_drop_over5pct_trap_is_tightened_with_asian_linkage():
    rules = load_rule_list(get_micro_rules_path())
    target = next(rule for rule in rules if rule.get("id") == "home_odds_drop_over5pct_trap")

    assert "asian['live_hv'] > asian['start_hv']" in target["condition"]
    assert "asian['giving_live_w'] <= 0.85" in target["condition"]
    assert target["prediction_bias"] == "平负"


def test_rule_draft_micro_rules_are_converted_to_runtime_context_syntax():
    rules = load_rule_list(get_micro_rules_path())
    rule_1 = next(rule for rule in rules if rule.get("id") == "micro_001")
    rule_2 = next(rule for rule in rules if rule.get("id") == "micro_002")

    assert " AND " not in rule_1["condition"]
    assert " AND " not in rule_2["condition"]
    assert "asian['giving_start_w']" in rule_1["condition"]
    assert "asian['giving_live_w']" in rule_1["condition"]
    assert "asian['start_hv']" in rule_2["condition"]
    assert "abs(asian['giving_live_w'] - asian['giving_start_w']) < 0.05" in rule_2["condition"]


def test_normalize_micro_rule_condition_converts_sql_like_draft_syntax():
    raw = "origin_handicap == '0.5' AND initial_water < 0.82 AND current_water BETWEEN 0.95 AND 1.05 AND handicap_change == 'up'"
    normalized = normalize_micro_rule_condition(raw)

    assert "AND" not in normalized
    assert "asian['start_hv'] == 0.5" in normalized
    assert "asian['giving_start_w'] < 0.82" in normalized
    assert "0.95 <= asian['giving_live_w'] <= 1.05" in normalized
    assert "asian['live_hv'] > asian['start_hv']" in normalized


def test_convert_draft_to_micro_rule_rejects_unsupported_signal_function():
    draft = {
        "draft_id": "IRL-2026-002",
        "title": "不兼容草稿",
        "target_scope": "micro_signal",
        "suggested_condition": "signal('deep_handicap_confidence') >= 0.8 AND signal('team_form_contradiction') IS TRUE",
        "suggested_action": "noop",
    }

    try:
        convert_draft_to_micro_rule(draft)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "signal(" in str(e)


def test_irl_2026_rules_are_no_longer_runtime_invalid():
    rules = load_rule_list(get_micro_rules_path())
    rule_1 = next(rule for rule in rules if rule.get("id") == "irl_2026_001")
    rule_2 = next(rule for rule in rules if rule.get("id") == "irl_2026_002")

    assert "AND" not in rule_1["condition"]
    assert "BETWEEN" not in rule_1["condition"]
    assert "asian['start_hv'] == 0.5" in rule_1["condition"]
    assert rule_2["enabled"] is False
    assert rule_2["condition"] == "False"
