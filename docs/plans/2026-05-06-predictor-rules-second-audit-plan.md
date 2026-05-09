# Predictor Rules Second Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 进一步审计并收敛 `predictor.py` 与 `rules.py` 中的逻辑错误、定义模糊和规则冲突，减少模型因术语漂移或规则重叠而做出不稳定判断。

**Architecture:** 当前核心问题已经从“单条规则写错”转向“多层定义并存”。本轮不追求新增功能，而是继续统一三套口径：`让球方/受让方`、`欧赔实力方`、`竞彩玩法方向`；同时把联赛经验、盘口检测文案、Agent C 附加硬约束收束成更稳定的层次结构，避免 Prompt 里多套近义规则并存。

**Tech Stack:** Python, OpenAI API, Streamlit, pytest, loguru

---

## 审计结论（当前已发现）

1. **联赛提示仍残留主队视角硬编码**
- `_get_league_hint()` 中仍有多条历史提示直接绑定“主队不败”“主队屠杀”“首选胜/平”等主队视角表达。
- 这些句子不是底层代码逻辑，但会直接进入 Prompt，容易把模型重新拉回“主队=上盘/优势方”的旧思维。
- 典型位置：
  - [predictor.py](file:///e:/zhangxuejun/football-prediction/src/llm/predictor.py#L1338-L1356)

2. **盘口信号文案仍混用“强队/实力方/让球方”**
- `_detect_half_ball_trap()`、`_detect_super_deep_dead_water()`、部分盘水背离文案仍使用“强队”作为盘口资金流向承载对象。
- 但当前全局定义已要求：盘口动作按亚赔让球方、强弱解释按欧赔实力方、玩法结算按竞彩方向。
- 这会让模型在读预警时收到模糊信号：到底是在说“强队热”还是“让球方热”。

3. **`_detect_euro_asian_divergence()` 仍带有过强动作结论**
- 虽然已统一欧赔强弱口径，但函数返回文案仍直接给出“必须防范谁不胜”“谁大概率能打出”这类强动作语句。
- 这类结论和 `P0/P1/DYNAMIC/risk_policy` 的动作层仍有交叉，后续容易再次出现“一处检测函数抢了最终裁决权”的问题。

4. **Agent C 额外硬约束继续膨胀**
- 当前 `final_prompt` 除了 `dynamic_rules` 外，还额外挂了：
  - 浅盘去重执行口径
  - 雷速伤停引用硬约束
  - 欧亚锚点硬约束
- 这些约束本身合理，但如果继续往这里叠，会再次形成第二个“隐形 rules.py”。

5. **盘型规则与联赛规则仍可能交叉改判**
- 例如 `沙特联赛`、`主流联赛`、`英冠` 的经验提示，仍在直接建议“推平/负”“首选胜/平”等动作。
- 这会和 `HANDICAP_RULES` 的盘口动作层互相重叠，尤其在浅盘/中盘场景里最危险。

6. **测试仍偏向局部函数，缺少 Prompt 层回归**
- 目前已有的测试覆盖了单个检测函数与 retry 约束，但还没有验证“动态规则 + Agent C 追加约束”最终拼接后是否出现口径冲突或重复指令。

---

### Task 1: 收敛联赛提示口径

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_league_hints_do_not_hardcode_home_team_bias():
    hint = LLMPredictor._get_league_hint("英超")
    assert "主队不败" not in hint
    assert "首选胜/平" not in hint
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_league_hints_do_not_hardcode_home_team_bias -v`

Expected: FAIL

**Step 3: 最小实现**

把联赛提示统一改成“补充因子”语气：
- 用“让球方/受让方/欧赔实力方/盘口示弱”替换“主队/客队/强队”
- 尽量少给最终推荐动作，多给“解释权重”

**Step 4: 再跑测试**

Run: `pytest tests/test_predictor_rules.py::test_league_hints_do_not_hardcode_home_team_bias -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "refactor: remove home-team bias from league hints"
```

### Task 2: 收敛盘口预警文案的对象定义

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_half_ball_trap_uses_giving_side_not_strong_team_wording():
    warning = LLMPredictor._detect_half_ball_trap(sample_asian, sample_odds)
    assert "强队" not in warning
    assert "让球方" in warning
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_half_ball_trap_uses_giving_side_not_strong_team_wording -v`

Expected: FAIL

**Step 3: 最小实现**

重点改以下函数中的输出文案：
- `_detect_super_deep_dead_water()`
- `_detect_half_ball_trap()`
- `_detect_handicap_water_divergence()`

原则：
- 盘口动作只写“让球方/受让方”
- 欧赔解释才写“实力方”
- 禁止同一句里混用“强队=让球方”的默认假设

**Step 4: 再跑测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "refactor: unify warning wording around giving side"
```

### Task 3: 把欧亚背离函数降级为“检测事实”

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Modify: `e:\zhangxuejun\football-prediction\src\llm\rules.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_euro_asian_divergence_returns_risk_description_not_final_verdict():
    warning = LLMPredictor._detect_euro_asian_divergence(sample_odds, sample_asian, sample_europe)
    assert "大概率能打出" not in warning
    assert "必须防范" not in warning
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_euro_asian_divergence_returns_risk_description_not_final_verdict -v`

Expected: FAIL

**Step 3: 最小实现**

将 `_detect_euro_asian_divergence()` 输出改成：
- 欧赔实力方是谁
- 理论应开什么盘口
- 实际亚指与理论相差多少
- 风险描述：偏“诱上/阻上/让步偏浅/让步偏深”

不要在该函数里直接下“必须推平/负”或“大概率打出”的最终裁决。

**Step 4: 同步调整 `rules.py`**

确保 `P0-4` 只规定“定义拆分 + 风险覆盖”，不让检测函数替代最终裁决。

**Step 5: 跑测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/llm/predictor.py src/llm/rules.py tests/test_predictor_rules.py
git commit -m "refactor: downgrade euro asian divergence to risk signal"
```

### Task 4: 收敛 Agent C 额外硬约束

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_final_prompt_does_not_duplicate_shallow_rules():
    prompt = build_final_prompt_for_test(...)
    assert prompt.count("浅盘") < 6
    assert "去重执行口径" in prompt
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_final_prompt_does_not_duplicate_shallow_rules -v`

Expected: FAIL

**Step 3: 最小实现**

抽一个辅助函数，例如：

```python
def _build_agent_c_guardrails(self, *, has_leisu_constraints, has_anchor_constraints):
    ...
```

把 `final_prompt` 中额外硬约束收口成：
- 通用硬约束
- 数据引用硬约束
- 去重执行口径

避免后续继续在 `predict()` 里直接追加大段 prompt 文本。

**Step 4: 跑测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "refactor: centralize agent c guardrails"
```

### Task 5: 增加 Prompt 层冲突回归测试

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 添加最小回归集**

```python
def test_dynamic_rules_do_not_repeat_shallow_action_language():
    ...

def test_league_hint_is_explanatory_not_final_pick():
    ...

def test_market_anchor_guardrail_exists_once():
    ...
```

**Step 2: 运行测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_predictor_rules.py
git commit -m "test: add prompt level regression coverage"
```

### Task 6: 人工复核真实样例

**Files:**
- Inspect: `e:\zhangxuejun\football-prediction\data\tmp_008_009_anchor_results.json`
- Inspect: `e:\zhangxuejun\football-prediction\data\today_matches.json`

**Step 1: 复跑指定样例**

Run: `python scripts/rerun_008_009_anchor.py`

Expected:
- `周三009` 仍能清晰区分“亚赔让球方”和“欧赔实力方”
- 浅盘相关文案不再重复堆叠

**Step 2: 人工检查最终文本**

确认以下项：
- 不再出现“主队视角”误导浅盘判断
- 欧亚背离更多是“风险描述”而不是“直接裁决”
- 联赛经验是补充因子，不是第二套动作规则

**Step 3: Commit**

```bash
git add data/tmp_008_009_anchor_results.json
git commit -m "test: verify prompt conflict cleanup on sample matches"
```
