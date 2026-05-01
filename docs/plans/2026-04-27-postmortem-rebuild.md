# 复盘报告功能重构计划

> **Goal:** 彻底根治复盘报告生成中的LLM幻觉问题（预测方向颠倒、预测内容捏造），建立"程序化准确计算 + LLM辅助洞察"的混合架构。

**Analysis Date:** 2026-04-27
**Status:** 📋 待执行

---

## 一、当前复盘系统的致命缺陷

### 🔴 缺陷 1：LLM 复盘报告的"主客颠倒"幻觉（与预测模型同源Bug）

**具体案例（04-26复盘）**：
- 模型预测：**平(60%) / 胜(40%)** → 主队不败
- 真实赛果：5-0 → 主队大胜，预测正确！
- 复盘LLM却说：**"预测平/胜，极度看好客队不败"** → 完全颠倒！

**根因分析**：
复盘LLM收到的数据格式是 `"全场预测推荐: 平(60%)/胜(40%)"`。LLM在阅读30场比赛的海量数据后，产生了"注意力漂移"：
- 它看到"平/胜"时，脑子里想的是"弱势方不败"
- 但没有正确地将"胜=主队胜"这个最基础的语义映射执行到位
- 导致复盘报告虚构了一个完全相反的"分析结论"

**本质**：这是预测模型中"P0-2 主客不颠倒"缺陷在复盘系统中的同源复制。

### 🔴 缺陷 2：LLM复盘报告没有任何事实性校验

当前流程：
```
30场比赛的原始数据 → LLM一次性生成 → 直接存储为report
```

没有中间任何一步验证：
- LLM声称的"预测准确率"是否与实际计算一致？ —— **从未校验**
- LLM声称的"某个案例预测了X"是否与数据库记录一致？ —— **从未校验**
- LLM提出的"优化建议"是否能对应到具体的错误模式？ —— **从未校验**

结果是：复盘报告变成了一篇"看起来专业但内容经常不准确的AI小作文"，无法作为可靠的优化输入。

### 🔴 缺陷 3：复盘LLM不知道哪些预测是正确的

当前Prompt（line 747-768）只是让LLM"总结今日预测的整体表现"，但没有告诉它：
- 哪些比赛预测正确了
- 哪些比赛预测错误了
- 正确率是多少
- 错误集中在哪种盘型
- 按联赛的准确率分布

LLM需要自己判断每场比赛的预测是否正确（在30场数据中），这导致了大量误判。

### 🟡 缺陷 4：`is_correct` 字段刚修复，历史数据仍为空

4个Phase已经修复了 `is_correct` 写回逻辑，但历史数据中该字段仍为空。复盘时LLM无法利用该字段。

---

## 二、重构方案：结构化复盘 + LLM辅助洞察

### 核心思路

**程序化层（确定性，100%准确）**：
1. 逐场计算预测是否正确（不让球/让球/半全场三个维度）
2. 汇总准确率（整体、按联赛、按盘型）
3. 列出错误案例（从数据库直接提取，不是LLM判断）

**LLM辅助层（创造性，需人工校对）**：
1. 收到**已计算好的准确统计数据**（而非原始比赛数据）
2. 收到**已确认的错误案例列表**（而非让LLM自己判断对错）
3. 只负责：识别错误模式、提出优化建议、发现冷门规律

### 具体实现

#### Step 1: 在 `run_post_mortem.py` 中新增 `compute_accuracy_report` 函数

```python
def compute_accuracy_report(date_str):
    """程序化计算准确率报告，返回结构化数据"""
    report = {
        "date": date_str,
        "overall": {"total": 0, "correct_nspf": 0, "correct_spf": 0, "correct_bqc": 0},
        "by_league": defaultdict(lambda: {"total": 0, "correct_nspf": 0}),
        "by_handicap_type": defaultdict(lambda: {"total": 0, "correct_nspf": 0}),
        "errors": [],  # 每条错误包含: match_num, home, away, score, prediction, actual
        "corrects": [] # 每条正确包含同样信息
    }
    
    # 1. 查询该日期所有已赛预测
    # 2. 逐场调用 calculate_actual_result 计算实际赛果
    # 3. 提取 NSPF/SPF 推荐，比对命中
    # 4. 填充 report dict
    # 5. 写回 is_correct 到数据库
    
    return report
```

#### Step 2: 在 `predictor.py` 中重写 `generate_post_mortem`

```python
def generate_post_mortem(self, date, accuracy_report):
    """
    V2: 基于程序化计算的准确率报告，让LLM只做洞察分析
    accuracy_report: compute_accuracy_report() 的输出
    """
    # 构建结构化数据摘要
    context = f"""【{date} 预测准确率报告 - 程序化计算】

## 整体统计
- 总场次: {overall['total']}
- 不让球命中率: {overall['correct_nspf']}/{overall['total']} = {rate_nspf}%
- 让球命中率: {overall['correct_spf']}/{overall['total']} = {rate_spf}%

## 按联赛准确率
{league_table}

## 按盘型准确率
{handicap_table}

## 错误案例清单（仅列出预测与实际完全不符的场次）
{errors_formatted}

## 正确案例清单
{corrects_formatted}
"""
    
    prompt = f"""
你是竞彩风控分析师。以下数据已经由程序精确计算，请直接基于这些数据进行洞察：

{context}

你的任务（严谨、客观、数据驱动）：
1. 识别错误集中在哪些联赛/盘型
2. 从错误案例中总结共性失败模式
3. 提出2-3条具体可执行的预测模型优化建议
4. **严禁**：捏造任何不在此报告中的预测内容，严禁说"模型预测了X"除非数据中确认是X
"""
```

#### Step 3: 重构 `src/pages/2_Post_Mortem.py` 的复盘展示

新的展示结构：
```
📊 程序化准确率统计 (纯数据，无LLM)
  ├── 整体准确率
  ├── 按联赛分布
  ├── 按盘型分布
  └── 错误案例表格 (可点击展开看完整预测原文)

🤖 LLM辅助洞察 (LLM生成，基于上述数据)
  ├── 错误模式识别
  └── 优化建议
```

#### Step 4: 新增数据校验断言

在LLM生成复盘文本后，增加基本事实校验：

```python
def validate_review(review_text, accuracy_report):
    """校验LLM生成的复盘是否存在明显的事实错误"""
    warnings = []
    # 校验1: 准确率数字是否一致
    # 校验2: 错误案例数量和比赛编号是否匹配
    # 校验3: 是否有明显的"主客颠倒"描述
    return warnings
```

---

## 三、文件变更清单

| 文件 | 操作 | 内容 |
|:---|:---|:---|
| `scripts/run_post_mortem.py` | 新增函数 | `compute_accuracy_report()` 程序化准确率计算 |
| `src/llm/predictor.py:714-784` | 重写 | `generate_post_mortem()` 改为接收结构化数据，LLM只做洞察 |
| `src/pages/2_Post_Mortem.py:212-270` | 重构 | 分离"数据展示"和"LLM洞察"，使用Tabs或分区 |
| `src/llm/predictor.py` | 新增方法 | `validate_review()` 复盘内容事实性校验 |

---

## 四、预期效果

| 指标 | 修复前 | 修复后 |
|:---|:---|:---|
| 复盘"主客颠倒"错误率 | 频繁发生 | **0%**（程序计算，不存在颠倒） |
| 预测方向捏造 | 频繁 | **0%**（LLM只收到已确认的正确/错误分类） |
| 准确率统计可信度 | 低 | **100%**（程序化计算） |
| 复盘作为优化输入的价值 | 低 | **高**（有数据支撑的洞察） |

---

## 五、执行任务清单

### Task 1: 新增 `compute_accuracy_report` 函数
**文件**: `scripts/run_post_mortem.py`
- 遍历当日所有预测记录
- 逐场计算实际赛果 vs 预测
- 汇总输出结构化dict

### Task 2: 重写 `generate_post_mortem`
**文件**: `src/llm/predictor.py:714-784`
- 改为接收 `accuracy_report` 而非原始比赛列表
- Prompt 改为"基于已计算数据做洞察"
- 增加反幻觉约束指令

### Task 3: 重构复盘展示页面
**文件**: `src/pages/2_Post_Mortem.py:212-300`
- 拆分"数据统计区"和"AI洞察区"
- 数据统计区使用 `st.metric` / `st.dataframe` 直接展示
- AI洞察区仅用于错误模式和优化建议

### Task 4: 新增复盘校验函数
**文件**: `src/llm/predictor.py`
- `validate_review()` 函数
- 在 `2_Post_Mortem.py` 中保存复盘前调用

### Task 5: 历史数据回填
- 运行 `run_post_mortem.py --backfill` 为历史数据回填 `is_correct`
