from src.llm.predictor import LLMPredictor
from scripts.run_post_mortem import (
    _build_agentc_mistake_hint,
    _dimension_review,
    _normalize_direction_tokens,
)


def _make_predictor():
    return object.__new__(LLMPredictor)


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class _Message:
            content = "## 四维方向对比总览\n- 测试复盘内容"

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


class _FakeDraftCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class _Message:
            content = """## 四维方向对比总览
- 测试复盘内容

## 结构化盘口复盘映射
```json
[
  {
    "case_id": "周四001",
    "match_num": "周四001",
    "matchup": "A vs B",
    "market_chain_summary": "半球盘降水不升盘，盘口链路仍不完整",
    "misread_type": "信息真空误判",
    "triggered_existing_rules": [],
    "disposition": "observe_only",
    "based_on_rule_id": "",
    "recommended_target_scope": "arbitration_guard",
    "recommended_title": "信息真空禁止预测",
    "market_review_complete": false,
    "entry_summary": "先补盘口链路，再决定是否立规"
  }
]
```

## 结构化规则草稿
```json
[
  {
    "case_id": "周四001",
    "draft_id": "draft_20260508_001",
    "title": "信息真空禁止预测",
    "target_scope": "arbitration_guard",
    "problem_type": "信息真空",
    "trigger_condition_nl": "当四维中少于2个维度形成有效方向时应回避",
    "suggested_condition": "ctx['informative_dimension_count'] < 2",
    "suggested_action": "abort_prediction",
    "suggested_bias": "",
    "priority": "high",
    "source_matches": ["周四001"],
    "disposition": "observe_only",
    "based_on_rule_id": "",
    "market_review_complete": false,
    "status": "draft",
    "created_at": "2026-05-08 10:30:00"
  }
]
```"""

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()


class _FakeDraftChat:
    def __init__(self):
        self.completions = _FakeDraftCompletions()


class _FakeDraftClient:
    def __init__(self):
        self.chat = _FakeDraftChat()


def test_normalize_direction_tokens_maps_common_labels():
    assert _normalize_direction_tokens("主队不败") == ["胜", "平"]
    assert _normalize_direction_tokens("平负") == ["平", "负"]
    assert _normalize_direction_tokens("客胜") == ["负"]


def test_dimension_review_marks_hit_wrong_and_insufficient():
    assert _dimension_review("平负", "负")["status"] == "命中"
    assert _dimension_review("胜", "负")["status"] == "错误"
    assert _dimension_review("未提取", "负")["status"] == "信息不足"


def test_build_agentc_mistake_hint_points_to_correct_dimensions():
    dim_reviews = {
        "基本面": {"is_correct": False},
        "盘赔": {"is_correct": True},
        "情报": {"is_correct": True},
        "微观规则": {"is_correct": None},
        "final": {"is_correct": False},
    }

    hint = _build_agentc_mistake_hint(dim_reviews, "情报力度不足却推翻了盘赔", "负")

    assert "本来更接近赛果的维度是：盘赔、情报" in hint
    assert "判断偏掉的维度是：基本面" in hint
    assert "情报力度不足却推翻了盘赔" in hint


def test_generate_post_mortem_includes_four_dimension_context():
    predictor = _make_predictor()
    predictor.client = _FakeClient()
    predictor.model = "test-model"

    accuracy_report = {
        "date": "2026-05-08",
        "batch_label": "2026-05-08 12:00 ~ 2026-05-09 12:00",
        "overall": {"total": 2, "correct_nspf": 1, "correct_spf": 1, "correct_bqc": 0},
        "by_league": {"欧罗巴": {"total": 2, "correct_nspf": 1}},
        "by_handicap": {"半球": {"total": 2, "correct_nspf": 1}},
        "matches": [
            {
                "match_num": "周四002",
                "home": "弗赖堡",
                "away": "布拉加",
                "league": "欧罗巴",
                "actual_score": "0:1",
                "actual_nspf": "负",
                "is_correct_nspf": False,
                "pred_nspf": "胜平",
                "asian_start": "0.88 | 半球 | 0.98",
                "asian_live": "0.96 | 半球/一球 | 0.86",
                "reason": "主队有题材，但盘口存在诱上风险。",
                "arb_fundamental": "胜平",
                "arb_market": "平负",
                "arb_intel": "平负",
                "arb_micro": "平负",
                "arb_final": "胜平",
                "arb_override_reason": "基本面主场优势被高估，错误推翻了盘赔与情报。",
                "agentc_mistake_hint": "本来更接近赛果的维度是：盘赔、情报、微观规则；Agent C 没有把更接近赛果的维度真正上升为最终仲裁。",
                "dim_reviews": {
                    "基本面": {"status": "错误"},
                    "盘赔": {"status": "命中"},
                    "情报": {"status": "命中"},
                    "微观规则": {"status": "命中"},
                    "final": {"status": "错误"},
                },
            },
            {
                "match_num": "周四003",
                "home": "利物浦",
                "away": "罗马",
                "league": "欧罗巴",
                "actual_score": "2:0",
                "actual_nspf": "胜",
                "is_correct_nspf": True,
                "pred_nspf": "胜",
                "asian_start": "0.82 | 半一 | 1.02",
                "asian_live": "0.76 | 一球 | 1.08",
                "reason": "盘赔与基本面同向。",
                "arb_fundamental": "胜",
                "arb_market": "胜",
                "arb_intel": "胜",
                "arb_micro": "未提取",
                "arb_final": "胜",
                "arb_override_reason": "无明显冲突，无需推翻",
                "agentc_mistake_hint": "Agent C 最终仲裁方向与实际赛果一致，本场不属于仲裁误判。",
                "dim_reviews": {
                    "基本面": {"status": "命中"},
                    "盘赔": {"status": "命中"},
                    "情报": {"status": "命中"},
                    "微观规则": {"status": "信息不足"},
                    "final": {"status": "命中"},
                },
            },
        ],
    }

    review_text = predictor.generate_post_mortem("2026-05-08", accuracy_report)
    prompt = predictor.client.chat.completions.last_kwargs["messages"][1]["content"]

    assert "## 📊 2026-05-08 12:00 ~ 2026-05-09 12:00 准确率统计" in review_text
    assert "四维方向命中对比" in prompt
    assert "四种方向结果对比（基于每场最后一次预测记录）" in prompt
    assert "Agent C 误判重点案例" in prompt
    assert "本来更接近赛果的维度是：盘赔、情报、微观规则" in prompt
    assert "输出用Markdown，分为\"四维方向对比总览\"" in prompt
    assert "逐场盘口复盘必须完整" in prompt
    assert "规则处置建议" in prompt
    assert "missing_market_review" in prompt


def test_generate_post_mortem_returns_rule_drafts_from_review():
    predictor = _make_predictor()
    predictor.client = _FakeDraftClient()
    predictor.model = "test-model"

    accuracy_report = {
        "date": "2026-05-08",
        "batch_label": "2026-05-08 12:00 ~ 2026-05-09 12:00",
        "overall": {"total": 1, "correct_nspf": 0, "correct_spf": 0, "correct_bqc": 0},
        "by_league": {"欧罗巴": {"total": 1, "correct_nspf": 0}},
        "by_handicap": {"半球": {"total": 1, "correct_nspf": 0}},
        "matches": [
            {
                "match_num": "周四001",
                "home": "A",
                "away": "B",
                "actual_score": "0:0",
                "actual_nspf": "平",
                "is_correct_nspf": False,
                "pred_nspf": "胜",
                "asian_start": "0.82 | 半球 | 1.02",
                "asian_live": "0.96 | 半球 | 0.86",
                "reason": "测试",
                "arb_fundamental": "未提取",
                "arb_market": "未提取",
                "arb_intel": "未提取",
                "arb_micro": "未提取",
                "arb_final": "胜",
                "arb_override_reason": "无明显冲突，无需推翻",
                "agentc_mistake_hint": "信息不足仍强行预测",
                "dim_reviews": {
                    "基本面": {"status": "信息不足"},
                    "盘赔": {"status": "信息不足"},
                    "情报": {"status": "信息不足"},
                    "微观规则": {"status": "信息不足"},
                    "final": {"status": "错误"},
                },
            }
        ],
    }

    review_text, rule_drafts, case_mappings = predictor.generate_post_mortem(
        "2026-05-08", accuracy_report, return_rule_drafts=True
    )
    prompt = predictor.client.chat.completions.last_kwargs["messages"][1]["content"]

    assert "四维方向对比总览" in review_text
    assert "结构化规则草稿" not in review_text
    assert "规则修正入口" in review_text
    assert isinstance(rule_drafts, list)
    assert isinstance(case_mappings, list)
    assert case_mappings[0]["case_id"] == "周四001"
    assert rule_drafts[0]["target_scope"] == "arbitration_guard"
    assert rule_drafts[0]["disposition"] == "observe_only"
    assert rule_drafts[0]["market_review_complete"] is False
    assert rule_drafts[0]["case_id"] == "周四001"
    assert "结构化盘口复盘映射" in prompt
    assert "结构化规则草稿" in prompt
    assert "严禁输出这些不兼容写法" in prompt
    assert "AND" in prompt
    assert "signal(...)" in prompt
    assert "disposition" in prompt
    assert "market_review_complete" in prompt


def test_validate_review_flags_missing_market_review_and_disposition():
    accuracy_report = {
        "overall": {"total": 1, "correct_nspf": 0, "correct_spf": 0, "correct_bqc": 0},
        "matches": [
            {
                "match_num": "周五012",
                "home": "莱万特",
                "away": "奥萨苏纳",
                "actual_nspf": "胜",
                "is_correct_nspf": False,
            }
        ],
    }

    review_text = """
## Agent C误判链路
### 周五012 | 莱万特 vs 奥萨苏纳
- 实际情况：赛果为胜。模型预测平负（错误）。
- Agent C误判分析：本场可能对盘口信号过度解读。
""".strip()

    is_valid, warnings = LLMPredictor.validate_review(review_text, accuracy_report)

    assert is_valid is False
    assert any("盘口复盘缺失" in warning for warning in warnings)
    assert any("规则处置建议缺失" in warning for warning in warnings)


def test_render_market_review_entries_outputs_rule_entry_section():
    entries = LLMPredictor._render_market_review_entries(
        [
            {
                "match_num": "周五005",
                "matchup": "埃夫斯堡 vs 布鲁马波",
                "disposition": "optimize_existing",
                "based_on_rule_id": "half_ball_water_drop_no_rise",
                "recommended_target_scope": "micro_signal",
                "entry_summary": "应收紧旧规则并补对冲保护规则",
            }
        ]
    )

    assert "规则修正入口" in entries
    assert "周五005" in entries
    assert "half_ball_water_drop_no_rise" in entries
    assert "optimize_existing" in entries
