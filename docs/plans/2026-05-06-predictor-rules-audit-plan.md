# Predictor Rules Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 梳理并重构 `predictor.py` 主预测链路与 `rules.py` 规则限制层，消除冲突、统一口径、让盘口判断与代码兜底保持一致。

**Architecture:** 当前系统把规则分散在 `rules.py`、`predictor.py` 的检测函数、Agent C 额外硬约束、以及 `retry_msgs` 代码兜底里，存在规则重复表达和动作漂移风险。优化方向是把“检测事实”和“执行动作”拆开，用统一的风控策略对象驱动 Prompt 注入与代码校验，减少同一规则在多处重复维护。

**Tech Stack:** Python, OpenAI API, Streamlit, pytest, JSON rules, loguru

---

### Task 1: 审计当前规则来源与冲突矩阵

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\docs\plans\2026-05-06-predictor-rules-audit-plan.md`
- Inspect: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Inspect: `e:\zhangxuejun\football-prediction\src\llm\rules.py`

**Step 1: 列出规则来源**

记录以下四类来源及其职责：
- `rules.py` 的 `P0/P1/DYNAMIC_CHANGE_RULES/HOT_MONEY_RULES`
- `predictor.py` 的检测函数，如 `_detect_euro_asian_divergence()`
- `predict()` 中的 Agent C 追加硬约束
- `predict()` 中的 `retry_msgs` 代码级兜底

**Step 2: 输出冲突矩阵**

至少列出以下冲突类型：
- 同一规则在 Prompt 和代码中重复表达，但阈值或动作不同
- 检测函数输出的预警方向，与 `P0/P1` 的推荐动作不一致
- “市场锚点”与“欧亚背离”使用的数据口径不同
- 盘型规则、联赛规则、历史错题召回同时生效时，是否会把同一方向过度放大

**Step 3: 记录审计结论**

把审计结果写进本计划文档的“审计结论”小节，后续重构只处理真实存在的冲突，不做泛化重写。

**Step 4: Commit**

```bash
git add docs/plans/2026-05-06-predictor-rules-audit-plan.md
git commit -m "docs: add predictor rules audit findings"
```

### Task 2: 抽离统一的风控策略对象

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_p0_4_policy_sets_double_pick_and_confidence_cap():
    policy = build_risk_policy(
        triggered_rule_ids=[],
        odds_conflict_text="存在冲突",
        has_anchor_divergence=True,
    )
    assert policy["confidence_cap"] == 60
    assert policy["force_double_nspf"] is True
    assert policy["force_double_rq"] is True
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_p0_4_policy_sets_double_pick_and_confidence_cap -v`

Expected: FAIL，因为 `build_risk_policy` 尚不存在。

**Step 3: 最小实现**

在 `predictor.py` 增加一个只负责“动作汇总”的方法，例如：

```python
def _build_risk_policy(self, *, triggered_rule_ids, odds_conflict_text, has_anchor_divergence):
    return {
        "confidence_cap": 60,
        "force_double_nspf": True,
        "force_double_rq": True,
        "must_explain_market_anchor": True,
    }
```

**Step 4: 再跑测试**

Run: `pytest tests/test_predictor_rules.py::test_p0_4_policy_sets_double_pick_and_confidence_cap -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "refactor: add unified predictor risk policy"
```

### Task 3: 统一“检测事实”与“执行动作”

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_retry_messages_are_built_from_policy_not_scattered_conditions():
    details = {
        "recommendation_nspf": "负",
        "recommendation_rq": "让负",
        "confidence": "80",
    }
    policy = {
        "force_double_nspf": True,
        "force_double_rq": True,
        "confidence_cap": 60,
        "must_explain_market_anchor": True,
    }
    msgs = build_retry_messages(details, policy, result_text="缺少市场锚点")
    assert any("双选" in msg for msg in msgs)
    assert any("60 或以下" in msg for msg in msgs)
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_predictor_rules.py::test_retry_messages_are_built_from_policy_not_scattered_conditions -v`

Expected: FAIL

**Step 3: 最小实现**

新增统一函数，如：

```python
def _build_retry_messages(self, details, policy, result_text):
    ...
```

把 `predict()` 中分散的 `P0-4`、微观信号、锚点解释约束逐步迁入这个函数，保留个别盘型特有校验即可。

**Step 4: 跑测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/llm/predictor.py tests/test_predictor_rules.py
git commit -m "refactor: centralize predictor retry message building"
```

### Task 4: 对齐欧亚锚点与欧亚背离的判断口径

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Modify: `e:\zhangxuejun\football-prediction\src\llm\rules.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_market_anchor_and_divergence_use_consistent_strength_source():
    # 构造欧赔客强、亚赔主让的样例
    match = {...}
    anchor = LLMPredictor._build_market_anchor_summary(match)
    warning = LLMPredictor._detect_odds_conflict(match["odds"], match["asian_odds"], match["europe_odds"])
    assert anchor["asian"]["side"] == "home"
    assert anchor["euro"]["side"] == "away"
    assert "亚赔实际让球方" in warning or warning
```

**Step 2: 运行测试确认失败或暴露歧义**

Run: `pytest tests/test_predictor_rules.py::test_market_anchor_and_divergence_use_consistent_strength_source -v`

Expected: 若逻辑漂移存在，测试会失败或断言不稳定。

**Step 3: 最小实现**

统一约定：
- “实力方”只能来自 `_resolve_euro_strength_side()`
- “让球方”只能来自 `_resolve_asian_giving_side()`
- `_detect_euro_asian_divergence()` 不再自行隐式定义强方动作，而是只返回“检测事实 + 风险描述”

**Step 4: 更新 `rules.py` 文案**

确保 `P0-4` 与 `predictor.py` 的策略对象一致，不再出现“Prompt 说一套，代码兜底另一套”。

**Step 5: 跑测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/llm/predictor.py src/llm/rules.py tests/test_predictor_rules.py
git commit -m "refactor: align market anchor and divergence logic"
```

### Task 5: 压缩并分层规则文本，减少 Prompt 内部打架

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\rules.py`
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`

**Step 1: 拆分规则层级**

把规则明确分成三层：
- `事实层`：盘口变化、欧亚冲突、微观信号触发
- `解释层`：阻上/诱上/控热/示弱 的判断提示
- `动作层`：双选、置信度上限、必须写出锚点

**Step 2: 删除重复动作描述**

重点删除这类重复：
- `P0-4` 里已有“双选+置信度上限”，Agent C 追加硬约束又重复要求
- `浅盘示弱诱下` 在 `P1`、`DYNAMIC_CHANGE_RULES`、代码 retry 三处同时强调

**Step 3: 保留最小必要文本**

原则：
- `rules.py` 负责给模型理解框架
- `predictor.py` 负责机器可执行的最终兜底
- 不在两个位置同时维护同一条“具体阈值”

**Step 4: Commit**

```bash
git add src/llm/rules.py src/llm/predictor.py
git commit -m "refactor: reduce duplicated predictor rule text"
```

### Task 6: 为核心冲突场景补回归测试

**Files:**
- Create: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 添加最小回归集**

至少覆盖这 5 类：

```python
def test_micro_signal_caps_confidence_at_65():
    ...

def test_p0_4_caps_confidence_at_60():
    ...

def test_p0_4_requires_double_pick():
    ...

def test_shallow_showweak_warning_keeps_home_win_option():
    ...

def test_market_anchor_retry_requires_explicit_asian_and_euro_labels():
    ...
```

**Step 2: 运行测试**

Run: `pytest tests/test_predictor_rules.py -v`

Expected: 全部 PASS

**Step 3: Commit**

```bash
git add tests/test_predictor_rules.py
git commit -m "test: add predictor rule conflict regression coverage"
```

### Task 7: 人工验收真实比赛样例

**Files:**
- Inspect: `e:\zhangxuejun\football-prediction\data\today_matches.json`
- Inspect: `e:\zhangxuejun\football-prediction\data\tmp_008_009_anchor_results.json`

**Step 1: 复跑指定场次**

Run: `python scripts/rerun_008_009_anchor.py`

Expected:
- `周三008`：亚赔与欧赔口径可解释
- `周三009`：明确写出“亚赔实际让球方=主队；欧赔实力方=客队”
- 若触发 `P0-4`，置信度必须 `<= 60`

**Step 2: 人工核查复盘链路**

确认复盘报告中是否优先输出：
- 盘口错误集中规律
- 盘口调度错因拆解
- 微观信号修正规则

**Step 3: Commit**

```bash
git add data/tmp_008_009_anchor_results.json
git commit -m "test: verify predictor conflict handling on match samples"
```

---

## 审计结论（当前已发现）

1. **规则分层过多，存在漂移风险**
- 同一规则同时存在于 `rules.py`、Agent C 追加硬约束、`retry_msgs` 代码兜底中。
- 结果是阈值和动作容易不同步，例如 `P0-4` 之前就出现“Prompt 要求 <60，但结果仍输出 80”。

2. **“检测事实”与“执行动作”耦合过深**
- `_detect_euro_asian_divergence()` 这类函数不仅判断是否背离，还直接携带“必须防哪边”的结论。
- 一旦 `P1` 或 `P0` 的动作策略变化，检测函数里的文案就会与全局动作层冲突。

3. **欧赔强弱口径存在双轨**
- `_resolve_euro_strength_side()` 用欧洲公司低赔投票定义“实力方”。
- `_detect_euro_asian_divergence()` 却仍然用 `竞彩不让球赔率(nspf)` 推导理论强方。
- 这会导致“市场锚点说客强，欧亚背离却按主强写解释”的潜在漂移。

4. **浅盘规则重复覆盖最严重**
- `rules.py` 的浅盘规则、`DYNAMIC_CHANGE_RULES`、`_detect_shallow_showweak_induce_down()`、以及 `retry_msgs` 都在管“示弱诱下/阻上”。
- 这类规则很容易产生“同一场比赛被多个相近逻辑同时推升主胜权重”的过拟合。

5. **历史错题召回缺少动作边界**
- `_recall_similar_errors()` 直接把“优先防冷”的错题警告注入 `dynamic_rules`，但没有明确优先级。
- 当它与当前盘型规则、联赛规则、微观信号方向相反时，模型可能收到互相拉扯的信息。

6. **测试覆盖不足**
- 当前仓库没有针对预测规则冲突的专门测试文件。
- 这会让后续继续加规则时，难以及时发现“新规则把旧规则推翻了”。

## 推荐优先级

1. 先做 `Task 2 + Task 3`
- 先把策略对象和统一 retry 构建抽出来，先止住规则漂移。

2. 再做 `Task 4`
- 把欧赔实力方与欧亚背离的强弱口径统一掉。

3. 最后做 `Task 5 + Task 6`
- 压缩文案层重复，再补回归测试，避免以后继续堆规则。
