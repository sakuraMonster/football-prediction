# Rule Feedback Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把复盘报告中验证过的错误模式沉淀为可审核、可采纳、可执行的规则闭环，让系统通过新增/收紧规则提升预测稳定性，而不是把复盘文本直接喂给 Agent C。

**Architecture:** 本轮改造把“复盘”从纯展示层升级为“规则候选生成层”。系统将新增两类可持久化规则：`micro_signals` 负责盘口微观方向判断，`arbitration_rules` 负责 Agent C 的预测资格和推翻边界；复盘页负责产出 `rule_drafts`，规则管理页负责审核/采纳，`predictor.py` 只执行结构化规则结果，不直接消费复盘长文。

**Tech Stack:** Python, Streamlit, OpenAI API, JSON rule files, pytest, loguru

---

## Scope

本计划只覆盖以下闭环：

1. 复盘报告可额外产出结构化候选规则草稿
2. 规则页可同时管理：
- `micro_signals.json`
- `arbitration_rules.json`
- `rule_drafts.json`
3. 预测器可读取并执行仲裁保护规则
4. Agent C 只消费规则执行结果，不直接读取复盘原文

本计划 **不** 包括：

1. 复杂历史回测面板
2. 自动直接上线草稿规则（仍保留人工审核）
3. 新建数据库表（先用 JSON 文件闭环）

---

### Task 1: 定义三类规则文件与统一 Schema

**Files:**
- Create: `e:\zhangxuejun\football-prediction\data\rules\arbitration_rules.json`
- Create: `e:\zhangxuejun\football-prediction\data\rules\rule_drafts.json`
- Modify: `e:\zhangxuejun\football-prediction\data\rules\micro_signals.json`
- Test: `e:\zhangxuejun\football-prediction\tests\test_rule_feedback_loop.py`

**Step 1: 写失败测试**

```python
import json
from pathlib import Path


def test_rule_files_exist_with_expected_top_level_shape():
    base = Path(r"e:\zhangxuejun\football-prediction\data\rules")
    micro = json.loads((base / "micro_signals.json").read_text(encoding="utf-8"))
    arbitration = json.loads((base / "arbitration_rules.json").read_text(encoding="utf-8"))
    drafts = json.loads((base / "rule_drafts.json").read_text(encoding="utf-8"))

    assert isinstance(micro, list)
    assert isinstance(arbitration, list)
    assert isinstance(drafts, list)
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py::test_rule_files_exist_with_expected_top_level_shape -v`

Expected: FAIL，因为 `arbitration_rules.json` 与 `rule_drafts.json` 尚不存在

**Step 3: 写最小实现**

新增两个空文件：

```json
[]
```

并为 `micro_signals.json` 预留两个新字段规范（本任务先不强制给所有旧规则补齐，只在注释文档和后续任务新增规则中使用）：
- `prediction_bias`
- `effect`

`arbitration_rules.json` 的最小 schema 约定：
- `id`
- `name`
- `category`
- `priority`
- `condition`
- `action_type`
- `action_payload`
- `explanation_template`
- `enabled`
- `source`

`rule_drafts.json` 的最小 schema 约定：
- `draft_id`
- `title`
- `target_scope`
- `problem_type`
- `trigger_condition_nl`
- `suggested_condition`
- `suggested_action`
- `suggested_bias`
- `priority`
- `source_matches`
- `status`
- `created_at`

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py::test_rule_files_exist_with_expected_top_level_shape -v`

Expected: PASS

**Step 5: Commit**

```bash
git add data/rules/micro_signals.json data/rules/arbitration_rules.json data/rules/rule_drafts.json tests/test_rule_feedback_loop.py
git commit -m "feat: add rule feedback loop storage files"
```

### Task 2: 在 `predictor.py` 增加仲裁保护规则加载器

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_load_arbitration_rules_reads_enabled_rules(tmp_path, monkeypatch):
    path = tmp_path / "arbitration_rules.json"
    path.write_text(
        '[{"id":"information_vacuum_abort","enabled":true,"priority":100}]',
        encoding="utf-8",
    )

    predictor = object.__new__(LLMPredictor)
    monkeypatch.setattr(LLMPredictor, "_get_arbitration_rules_path", lambda self: str(path))

    rules = predictor._load_arbitration_rules()
    assert rules[0]["id"] == "information_vacuum_abort"
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_load_arbitration_rules_reads_enabled_rules -v`

Expected: FAIL，因为 `_load_arbitration_rules()` 与 `_get_arbitration_rules_path()` 尚不存在

**Step 3: 写最小实现**

在 `predictor.py` 新增：

```python
def _get_arbitration_rules_path(self):
    ...

def _load_arbitration_rules(self):
    ...
```

实现要求：
- 只读取 `enabled != false` 的规则
- 按 `priority` 倒序排序
- 文件缺失时返回空列表，不抛异常

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_load_arbitration_rules_reads_enabled_rules -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "feat: load arbitration guard rules in predictor"
```

### Task 3: 在 `predictor.py` 构建仲裁规则上下文与执行器

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_evaluate_arbitration_rules_aborts_on_information_vacuum():
    predictor = object.__new__(LLMPredictor)
    ctx = {"all_dimensions_empty": True}
    predictor._load_arbitration_rules = lambda: [
        {
            "id": "information_vacuum_abort",
            "priority": 100,
            "condition": "ctx['all_dimensions_empty'] is True",
            "action_type": "abort_prediction",
            "action_payload": {"message": "信息不足以形成预测，建议回避", "confidence": 0},
            "enabled": True,
        }
    ]

    result = predictor._evaluate_arbitration_rules(ctx)
    assert result["abort_prediction"] is True
    assert result["message"] == "信息不足以形成预测，建议回避"
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_evaluate_arbitration_rules_aborts_on_information_vacuum -v`

Expected: FAIL，因为 `_evaluate_arbitration_rules()` 尚不存在

**Step 3: 写最小实现**

新增：

```python
def _build_arbitration_rule_context(...):
    ...

def _evaluate_arbitration_rules(self, ctx):
    ...
```

第一版只支持以下 `action_type`：
- `abort_prediction`
- `force_double`
- `cap_confidence`
- `forbid_override`
- `require_override_reason`

返回结构统一为：

```python
{
    "abort_prediction": False,
    "must_double_nspf": False,
    "must_double_rq": False,
    "confidence_cap": None,
    "override_blocked": False,
    "guard_messages": [],
    "message": "",
}
```

**Step 4: 再补一条失败测试**

```python
def test_evaluate_arbitration_rules_blocks_override_when_market_and_micro_align():
    predictor = object.__new__(LLMPredictor)
    ctx = {
        "market_micro_aligned": True,
        "reverse_only_from_fundamental_or_intel": True,
    }
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

    result = predictor._evaluate_arbitration_rules(ctx)
    assert result["override_blocked"] is True
```

**Step 5: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -k arbitration_rules -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "feat: evaluate arbitration guard rules before final prediction"
```

### Task 4: 把仲裁规则执行结果接到 Agent C 输出后处理层

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_apply_arbitration_actions_returns_skip_text_when_abort_prediction():
    predictor = object.__new__(LLMPredictor)
    text = "## 🎯 最终预测\n- **竞彩推荐**：胜(55%)/平(45%)"
    details = {"confidence": "58"}
    actions = {
        "abort_prediction": True,
        "message": "信息不足以形成预测，建议回避",
        "confidence_cap": 0,
    }

    new_text = predictor._apply_arbitration_actions(text, details, actions)
    assert "建议回避" in new_text
    assert "竞彩推荐" not in new_text or "暂无" in new_text
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_apply_arbitration_actions_returns_skip_text_when_abort_prediction -v`

Expected: FAIL，因为 `_apply_arbitration_actions()` 尚不存在

**Step 3: 写最小实现**

新增：

```python
def _apply_arbitration_actions(self, result_text, details, actions):
    ...
```

约束：
- `abort_prediction=True` 时，不做“改成另一个方向”的硬纠偏
- 仅改成回避文本或“暂无有效预测”
- `force_double` / `cap_confidence` 继续沿用现有最小兜底思想，不新增方向硬覆盖

**Step 4: 在 `predict()` 里接线**

在 Agent C 返回并解析细节后：
1. 先构建 `ctx`
2. 再执行 `_evaluate_arbitration_rules(ctx)`
3. 最后 `_apply_arbitration_actions(...)`

要求：
- 不替代已有 `risk_policy`
- 只在“资格/边界”层生效

**Step 5: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -k "arbitration_actions or arbitration_rules" -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "feat: apply arbitration guard actions to final prediction"
```

### Task 5: 让复盘报告额外产出结构化 `rule_drafts`

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\2_Post_Mortem.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_post_mortem_report.py`

**Step 1: 写失败测试**

```python
def test_generate_post_mortem_returns_rule_drafts_from_review():
    predictor = object.__new__(LLMPredictor)
    predictor.client = fake_client_returning_review_with_rule_suggestions()
    predictor.model = "test-model"

    review_text, rule_drafts = predictor.generate_post_mortem("2026-05-08", sample_accuracy_report, return_rule_drafts=True)

    assert "四维方向对比总览" in review_text
    assert isinstance(rule_drafts, list)
    assert rule_drafts[0]["target_scope"] in {"warning", "micro_signal", "arbitration_guard"}
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_post_mortem_report.py::test_generate_post_mortem_returns_rule_drafts_from_review -v`

Expected: FAIL，因为 `generate_post_mortem()` 当前只返回字符串

**Step 3: 写最小实现**

改造 `generate_post_mortem()`：
- 默认保持兼容：仍可只返回 `review_text`
- 增加可选参数：`return_rule_drafts=False`
- 当 `True` 时，返回：

```python
(review_text, rule_drafts)
```

`rule_drafts` 第一版不要求完全自动解析自然语言段落，可直接让 LLM 在复盘正文后追加一个固定的 JSON 区块，例如：

```markdown
## 结构化规则草稿
```json
[
  ...
]
```
```

再由代码安全提取 JSON。

**Step 4: 在 `2_Post_Mortem.py` 接线**

调用方式改为：

```python
review_text, rule_drafts = predictor.generate_post_mortem(..., return_rule_drafts=True)
```

并在保存复盘后调用新的 `save_rule_drafts(...)`

**Step 5: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_post_mortem_report.py -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/llm/predictor.py src/pages/2_Post_Mortem.py tests/test_post_mortem_report.py
git commit -m "feat: generate structured rule drafts from post mortem"
```

### Task 6: 新增规则草稿文件读写工具

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\pages\2_Post_Mortem.py`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\5_Rule_Manager.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_rule_feedback_loop.py`

**Step 1: 写失败测试**

```python
def test_save_rule_drafts_persists_new_items(tmp_path):
    path = tmp_path / "rule_drafts.json"
    save_rule_drafts(
        path=str(path),
        drafts=[{"draft_id": "draft_001", "status": "draft"}],
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["draft_id"] == "draft_001"
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py::test_save_rule_drafts_persists_new_items -v`

Expected: FAIL

**Step 3: 写最小实现**

新增小工具函数（可放在 `5_Rule_Manager.py` 顶部或抽到独立 util）：
- `load_rule_drafts(path)`
- `save_rule_drafts(path, drafts)`
- `append_rule_drafts(path, drafts)`

要求：
- 以 `draft_id` 去重
- 已存在的 `accepted` / `rejected` 草稿不重复插入

**Step 4: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/pages/2_Post_Mortem.py src/pages/5_Rule_Manager.py tests/test_rule_feedback_loop.py
git commit -m "feat: add rule draft persistence helpers"
```

### Task 7: 升级规则管理页为三类规则视图

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\pages\5_Rule_Manager.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_rule_feedback_loop.py`

**Step 1: 写失败测试**

```python
def test_convert_draft_to_arbitration_rule():
    draft = {
        "title": "信息真空禁止预测",
        "target_scope": "arbitration_guard",
        "suggested_condition": "ctx['all_dimensions_empty'] is True",
        "suggested_action": "abort_prediction",
    }

    rule = convert_draft_to_rule(draft, target_scope="arbitration_guard")
    assert rule["category"] == "arbitration_guard"
    assert rule["action_type"] == "abort_prediction"
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py::test_convert_draft_to_arbitration_rule -v`

Expected: FAIL

**Step 3: 写最小实现**

在规则页增加：
- `tab_micro`
- `tab_arbitration`
- `tab_drafts`

并新增转换函数：
- `convert_draft_to_micro_rule(draft)`
- `convert_draft_to_arbitration_rule(draft)`

`tab_drafts` 每条草稿提供按钮：
- `采纳为微观规则`
- `采纳为仲裁规则`
- `忽略`

**Step 4: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py -k convert_draft -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/pages/5_Rule_Manager.py tests/test_rule_feedback_loop.py
git commit -m "feat: manage micro rules arbitration rules and drafts in one page"
```

### Task 8: 在复盘页展示候选规则草稿并支持一键采纳

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\pages\2_Post_Mortem.py`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\5_Rule_Manager.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_rule_feedback_loop.py`

**Step 1: 写失败测试**

```python
def test_post_mortem_page_can_filter_drafts_for_target_date():
    drafts = [
        {"draft_id": "d1", "source_matches": ["周四003"], "status": "draft"},
        {"draft_id": "d2", "source_matches": ["周四005"], "status": "accepted"},
    ]
    visible = [d for d in drafts if d["status"] == "draft"]
    assert len(visible) == 1
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py::test_post_mortem_page_can_filter_drafts_for_target_date -v`

Expected: FAIL（先用它驱动页面逻辑抽函数）

**Step 3: 写最小实现**

在复盘页新增一段：
- 标题：`候选规则草稿`
- 每条展示：
  - `title`
  - `target_scope`
  - `problem_type`
  - `source_matches`
  - `trigger_condition_nl`
- 提供跳转按钮：
  - `去规则页审核`

第一版不直接在复盘页完成最终采纳，只做展示和跳转，避免页面逻辑过重。

**Step 4: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_rule_feedback_loop.py -k draft -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/pages/2_Post_Mortem.py src/pages/5_Rule_Manager.py tests/test_rule_feedback_loop.py
git commit -m "feat: surface rule drafts in post mortem page"
```

### Task 9: 首批规则样例入库

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\data\rules\arbitration_rules.json`
- Modify: `e:\zhangxuejun\football-prediction\data\rules\micro_signals.json`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_arbitration_rules_seed_contains_information_vacuum_abort():
    predictor = object.__new__(LLMPredictor)
    rules = predictor._load_arbitration_rules()
    assert any(rule["id"] == "information_vacuum_abort" for rule in rules)
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_arbitration_rules_seed_contains_information_vacuum_abort -v`

Expected: FAIL

**Step 3: 写最小实现**

首批只落 3 条：
- `information_vacuum_abort`
- `weak_evidence_cannot_override_market`
- 收紧版 `home_odds_drop_over5pct_trap`

先不要一口气把全部复盘建议都写进去。

**Step 4: 跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -k "information_vacuum_abort or home_odds_drop" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add data/rules/arbitration_rules.json data/rules/micro_signals.json tests/test_predictor_rules.py
git commit -m "feat: seed first post mortem derived rules"
```

### Task 10: 全链路验收

**Files:**
- Inspect: `e:\zhangxuejun\football-prediction\src\pages\2_Post_Mortem.py`
- Inspect: `e:\zhangxuejun\football-prediction\src\pages\5_Rule_Manager.py`
- Inspect: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Inspect: `e:\zhangxuejun\football-prediction\data\rules\*.json`

**Step 1: 跑定向测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_post_mortem_report.py tests/test_predictor_rules.py tests/test_rule_feedback_loop.py -v`

Expected: PASS（若环境缺少 pytest，则至少逐个执行新测试函数并记录结果）

**Step 2: 检查诊断**

检查：
- `src/llm/predictor.py`
- `src/pages/2_Post_Mortem.py`
- `src/pages/5_Rule_Manager.py`

Expected: 无新增诊断错误

**Step 3: 人工验收页面**

验收路径：
- 进入 `Post_Mortem`
- 生成复盘
- 确认出现 `候选规则草稿`
- 进入规则管理页
- 能看到 `微观规则 / 仲裁规则 / 候选草稿` 三个视图
- 采纳一条草稿后刷新页面，确认目标规则库已写入

**Step 4: Commit**

```bash
git add src/pages/2_Post_Mortem.py src/pages/5_Rule_Manager.py src/llm/predictor.py data/rules/*.json tests/*.py
git commit -m "feat: close the post mortem to rule feedback loop"
```

---

## 实施后的系统边界

改造完成后，系统边界应固定为：

1. `复盘页`
- 负责错误拆解
- 负责生成候选规则草稿

2. `规则页`
- 负责审核和采纳规则
- 不直接承担预测逻辑

3. `predictor.py`
- 负责执行 `micro_signals` 与 `arbitration_rules`
- 只把结构化结果传给 Agent C

4. `Agent C`
- 只做解释与最终表达
- 不直接学习复盘原文

---

## 首批验收目标

上线本闭环后，至少验证以下三项是否改善：

1. `信息真空强行预测` 显著减少
2. `升盘升水阻上误判成诱上` 的案例减少
3. `欧赔 trap 仅凭赔率降幅触发` 的误伤率下降
