# 预测模型针对“僵尸盘”与“退盘”误判的深度优化方案

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 针对近期复盘报告（04-30及后续），修复大模型对于“平半僵尸盘”（真实阻上被误判为诱上）和“半球退平半”（真实降温被误判为看衰）的严重方向性误读。

**Architecture:** 
1.  **升级微观信号引擎 (`_analyze_micro_market_signals`)**: 将先前仅作软提示的分析结果强化为红色高危预警 (🔴)，明确“平局输半”的博弈门槛，并增加更多细颗粒度的条件判断。
2.  **强化动态路由规则 (`rules.py`)**: 将这些误判规律硬编码到 `HANDICAP_RULES["0.25_0.5"]` 浅盘规则中，逼迫模型用“舒适度/阻力”视角代替“降水/升水 = 看好看衰”的线性视角。
3.  **增加代码级强制纠错 (`predictor.py -> predict`)**: 针对“平半满水僵尸盘”，如果模型仍然被表象迷惑给出“平/负”，触发与“浅盘示弱诱下”类似的兜底重试机制，强制要求保留“胜”的可能。

**Tech Stack:** Python, Prompt Engineering, LLM (OpenAI API)

---

### Task 1: 强化微观信号分析器的预警级别与解释力

**Files:**
- Modify: `src/llm/predictor.py` (重点修改 `_analyze_micro_market_signals` 方法)

**Step 1: 增强降温型退盘的输出提示**

修改 `_analyze_micro_market_signals` 中的降温型退盘逻辑，加上预警图标，并强调机构真实意图：

```python
        if hs == 0.5 and hl == 0.25 and giving_start_w <= 0.80 and 0.85 <= giving_live_w <= 0.95:
            cup_hint = "（欧战场景：主场优势与赛程动机权重更高）" if is_euro_cup else ""
            lines.append(
                f"🔴 **【微观信号：降温型退盘】** 初盘半球超低水({giving_start_w:.2f})已强表达优势，退至平半中水({giving_live_w:.2f})是典型的控热、平衡筹码操作{cup_hint}。**请勿线性等同于“看衰让球方”**。这往往是机构真实的保护行为，主队不败概率极高。"
            )
```

**Step 2: 增强阻上型僵持（平半僵尸盘）的判定与输出**

细化平半满水的判定，明确指出“平局输半”的风险，点破“诱上”幻觉：

```python
        if hs == hl and hl == 0.25 and giving_live_w >= 1.00:
            draw_risk = ""
            if p_draw is not None and p_draw >= 0.28:
                draw_risk = f"（欧赔隐含平局约{p_draw:.0%}，平半盘下平局即输半，这让买入上盘变得极其不舒服且风险极高）"
            protect = ""
            if receiving_live_w <= 0.85:
                protect = f"；下盘受让低水({receiving_live_w:.2f})反而在提供舒适的保护"
            lines.append(
                f"🔴 **【微观信号：阻上型僵持 (僵尸盘)】** 平半盘口不变但上盘维持满水/高水({giving_live_w:.2f}){draw_risk}{protect}。这绝不是简单的“高回报诱上”，而是通过高风险+不舒服的水位设置**真实的阻力**。机构在赶赶筹码去下盘，**让球方极大概率能打出，严禁单博下盘！**"
            )
```

### Task 2: 更新浅盘动态规则，注入“舒适度/阻力”视角

**Files:**
- Modify: `src/llm/rules.py` (修改 `HANDICAP_RULES["0.25_0.5"]`)

**Step 1: 在浅盘规则中增加对“平半满水僵尸盘”和“半球退平半”的强制约定**

```python
    "0.25_0.5": """
### 🔵 浅盘风控专属铁律 (平半/半球核心)
- **【平半满水僵尸盘 (真实阻力误判预警)】**：当初盘平半，即时盘仍为平半，但上盘水位高达满水(1.00以上)时，**绝对禁止将其粗暴解读为“机构利用高回报诱上”**！在平半盘下，平局会输掉一半本金，满水往往是机构设置的**真实阻力**（让买上盘的人感到极其不舒服且高风险），下盘反而受到低水保护。此时机构真实意图是**阻上**，主队赢球概率极高！
- **【半球低水退平半中水 (真实降温误判预警)】**：当初盘开出半球且伴随超低水(如0.78)，说明初盘已给予强力支持。临场退盘至平半中水，这是标准的**“降温/平衡筹码”**操作，旨在打压上盘热度。**绝对禁止将其解读为“让步无力/信心崩塌”**。此形态下让球方依然是绝对优势方。
- **【示弱诱下核心逻辑】**：当盘口出现“退盘、无力升盘”时，必须反问一句：下盘受让是不是变得过于舒适（受让 + 低水）？如果是，这就是机构在驱赶热度去下盘的“阻上/诱下”手法，必须防范让球方直接赢球！
""",
```

### Task 3: 针对“平半满水僵尸盘”增加代码级兜底重试

**Files:**
- Modify: `src/llm/predictor.py` (修改 `predict` 方法)

**Step 1: 在 `predict` 中解析微观信号，提取僵尸盘标记**

在 `Agent C` 最终裁决前，已经生成了微观信号。我们需要将其提取为一个布尔值：

```python
            # ... 前面的代码
            micro_signals = self._analyze_micro_market_signals(match_data.get("odds", {}), match_data.get("asian_odds", {}), match_data.get('league', ''))
            is_zombie_pan = "阻上型僵持" in micro_signals
```

**Step 2: 在第一次预测结果返回后，执行强校验**

```python
            # ... Agent C 初次预测完成，获取 result
            
            # 原有的浅盘示弱重试逻辑 ...
            
            # 新增平半僵尸盘强制重试逻辑
            if is_zombie_pan:
                details = self.parse_prediction_details(result)
                nspf_rec = details.get("recommendation_nspf", "") or ""
                # 如果是主让平半，判断推荐是否包含胜
                macau_start = match_data.get("asian_odds", {}).get("macau", {}).get("start", "")
                is_home_giving = ("受" not in macau_start) and ("|" in macau_start)
                
                if is_home_giving and "胜" not in nspf_rec:
                    logger.warning("检测到平半满水僵尸盘，但模型误判为平/负，触发强制纠错重试！")
                    retry_prompt = final_prompt + f"""

### 🔴 纠错指令（必须无条件执行）
系统已触发【平半僵尸盘（阻上型僵持）预警】：
在这个盘口下，平局输半且上盘满水，是极其强烈的**真实阻力**设置，而非诱上！
你刚才的不让球推荐未包含“胜”，这是严重的“阻上/诱上颠倒”误判。
现在必须重新输出最终预测，并满足以下硬约束：
1) **不让球推荐必须包含“胜”**（例如：胜(50%)/平(50%) 或 胜(60%)/负(40%)）。
2) **绝对禁止单纯输出“平/负”**。
3) 请在【盘赔深度解析】中明确指出这是“真实阻上”。
"""
                    agent_c_retry = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": retry_prompt}],
                        temperature=0.1,
                    )
                    result = agent_c_retry.choices[0].message.content
```

---
**Review & Handoff:** 该方案直接针对导致最近两场比赛误判的底层逻辑漏洞，从“解释层（微观信号）”、“规则层（Prompt）”和“兜底层（代码重试）”进行了全方位堵漏。
