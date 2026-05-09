# Football Parlay Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将主界面的足球 AI 串关功能从“LLM 自由编排五套方案”重构为“程序分池选场 + 固定三套模板 + 稳健盈利优先”的可控方案生成器。

**Architecture:** 本轮改造保留单场预测结果作为上游输入，但把串关阶段拆成候选标准化、规则打分、分池组装和结果渲染四层。`predictor.py` 负责候选评分和三套方案组装，`1_Dashboard.py` 负责传入融合后的汇总数据并展示结果，测试覆盖三套结构、候选分池和全局重复暴露约束。

**Tech Stack:** Python, Streamlit, OpenAI API, pytest, loguru

---

## Scope

本计划只覆盖足球主界面上的“AI 智能生成三套实战串子单”功能：

1. 统一改成固定三套方案：主推稳健单 / 平衡增益单 / 利润冲击单
2. 将 `combined_summary_data` 真正接入串关生成流程
3. 在 `predictor.py` 增加候选构建、评分、分池、组装与渲染逻辑
4. 增加串关相关测试，保证结构稳定和重复暴露可控

本计划 **不** 包括：

1. 篮球串关功能改造
2. 历史回测与自动调参系统
3. 数据库 Schema 变更
4. 串关页面大规模 UI 重做

### Task 1: 固化产品规则并修正文档入口

**Files:**
- Create: `e:\zhangxuejun\football-prediction\docs\plans\2026-05-09-football-parlay-refactor-plan.md`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\1_Dashboard.py`

**Step 1: 明确方案职责**

将串关产品定义为三套固定模板：

```text
A 主推稳健单：2串1，只从稳胆池选
B 平衡增益单：2串1，1场稳胆 + 1场价值场
C 利润冲击单：2串1，1场稳胆 + 1场博胆
```

**Step 2: 修正页面接入**

把：

```python
new_parlays = predictor.generate_parlays(summary_data)
```

改为：

```python
new_parlays = predictor.generate_parlays(combined_summary_data)
```

并同步优化按钮/提示文案，避免页面“三套”与底层“五套”继续冲突。

### Task 2: 在 `predictor.py` 新增候选标准化与评分器

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_build_parlay_candidates_generates_scored_entries():
    predictor = object.__new__(LLMPredictor)
    candidates = predictor._build_parlay_candidates([sample_match()])
    assert len(candidates) == 1
    assert candidates[0]["scores"]["stable"] >= 0
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_build_parlay_candidates_generates_scored_entries -v`

Expected: FAIL，因为 `_build_parlay_candidates()` 尚不存在

**Step 3: 写最小实现**

新增以下方法：

```python
def _build_parlay_candidates(self, summary_data):
    ...

def _score_parlay_candidate(self, match):
    ...
```

实现要求：

1. 读取 `summary_data` 中的推荐、赔率、置信度、理由、进球数
2. 计算 `stable/value/aggressive/penalty`
3. 生成候选标签：`stable/value/aggressive/banned`

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_build_parlay_candidates_generates_scored_entries -v`

Expected: PASS

### Task 3: 在 `predictor.py` 增加分池与三套方案组装器

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_compose_three_parlay_plans_returns_fixed_templates():
    predictor = object.__new__(LLMPredictor)
    plans = predictor._compose_three_parlay_plans(sample_candidates())
    assert [p["plan_code"] for p in plans] == ["A", "B", "C"]
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_compose_three_parlay_plans_returns_fixed_templates -v`

Expected: FAIL，因为 `_compose_three_parlay_plans()` 尚不存在

**Step 3: 写最小实现**

新增：

```python
def _bucketize_parlay_candidates(self, candidates):
    ...

def _compose_three_parlay_plans(self, candidates):
    ...
```

实现要求：

1. `A` 固定 `2串1`，优先取两场稳胆
2. `B` 固定 `2串1`，取 1 稳胆 + 1 价值场
3. `C` 固定 `2串1`，取 1 稳胆 + 1 博胆
4. 同一场在三套里最多出现 2 次
5. 若池子不足，按优先级回退，但仍保持三套结构

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_compose_three_parlay_plans_returns_fixed_templates -v`

Expected: PASS

### Task 4: 重写 `generate_parlays()` 为规则驱动输出

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Test: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 写失败测试**

```python
def test_generate_parlays_outputs_three_fixed_sections():
    predictor = object.__new__(LLMPredictor)
    text = predictor.generate_parlays(sample_summary_data())
    assert "### 方案A：主推稳健单" in text
    assert "### 方案B：平衡增益单" in text
    assert "### 方案C：利润冲击单" in text
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_generate_parlays_outputs_three_fixed_sections -v`

Expected: FAIL，因为当前仍输出五套自由格式方案

**Step 3: 写最小实现**

将 `generate_parlays()` 改成：

1. 调用 `_build_parlay_candidates()`
2. 调用 `_compose_three_parlay_plans()`
3. 通过 `_render_parlay_markdown()` 输出稳定 Markdown
4. 保留错误处理与日志

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py::test_generate_parlays_outputs_three_fixed_sections -v`

Expected: PASS

### Task 5: 补充重复暴露与进球数接入测试

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\1_Dashboard.py`

**Step 1: 写失败测试**

```python
def test_compose_three_parlay_plans_limits_match_reuse_to_two_times():
    ...

def test_generate_parlays_prefers_ai_goals_when_present():
    ...
```

**Step 2: 运行测试确认失败**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -k "parlay" -v`

Expected: FAIL，因为尚未实现暴露限制与专项进球数消费逻辑

**Step 3: 写最小实现**

1. 在组装器里增加全局计数器
2. 渲染时优先读取 `AI预测进球数`
3. 页面层改传 `combined_summary_data`

**Step 4: 再跑测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -k "parlay" -v`

Expected: PASS

### Task 6: 回归验证与诊断检查

**Files:**
- Modify: `e:\zhangxuejun\football-prediction\src\llm\predictor.py`
- Modify: `e:\zhangxuejun\football-prediction\src\pages\1_Dashboard.py`
- Modify: `e:\zhangxuejun\football-prediction\tests\test_predictor_rules.py`

**Step 1: 运行目标测试**

Run: `C:\Users\zhangxuejun\AppData\Local\Programs\Python\Python38\python.exe -m pytest tests/test_predictor_rules.py -v`

Expected: PASS

**Step 2: 检查诊断**

使用编辑器诊断确认本轮修改未引入新的语法或类型错误。

**Step 3: Commit**

```bash
git add docs/plans/2026-05-09-football-parlay-refactor-plan.md src/llm/predictor.py src/pages/1_Dashboard.py tests/test_predictor_rules.py
git commit -m "feat: refactor football parlays into fixed three-plan engine"
```
