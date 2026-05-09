import json
import tempfile
from pathlib import Path

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
