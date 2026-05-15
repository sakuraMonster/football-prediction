# Market Script Engine v2（欧亚盘口剧本）旁路接入实施方案

> **Goal:** 在不改变现有主界面与主预测输出的前提下，于同仓库新增“Market Script Engine v2”，以 Shadow Mode 旁路接入预测链路，实现可回测、可监控、可灰度升级的欧亚盘口剧本体系。

## 1. 约束与原则

### 1.1 明确约束

- 同仓库旁路接入
- 新体系与旧代码隔离（目录隔离 + 数据表隔离 + 配置隔离）
- 现有主界面功能不变（Dashboard/预测流程/Rule Manager 不被破坏）

### 1.2 设计原则

- 默认 Shadow：只计算与落库，不改变 `dynamic_rules`、不改变最终推荐
- 方向输出稀缺化：仅白名单子类满足强条件才允许 Direction，其余 Risk/Diagnosis
- 评价顺序：CLV 优先，再看赢盘/赛果 lift，全部做样本外分层

## 2. 新体系预测链路（v2）端到端

### 2.1 在线阶段（predict 时旁路执行）

1) 从 `match_data` 提取 `fixture_id/league/match_time` 与当前欧亚盘口（用于兜底）
2) 从 v2 专用表拉取该场赔率时间序列（open/T-24/T-6/T-1/close），若不足则降级
3) 主线盘口选择（每桶选择覆盖最高且最接近 50-50 的 AH）
4) 欧赔去水概率与亚盘特征生成
5) 计算 market 共识与分歧度（dispersion/convergence）
6) 原型/子类识别（prototype/subclass）
7) 动作与强度（Direction/Risk/Diagnosis + strong/medium/weak）
8) 若允许 Direction：执行“跟欧/跟亚/跟收盘”的裁决并给出 direction_hint
9) 输出写入 `v2_script_output`（带 version、mode=shadow）

### 2.2 离线阶段（采样与监控）

- 赛前滚动采样脚本：持续写入 `v2_odds_snapshot/v2_ah_snapshot`
- 监控任务：按子类/联赛/窗口计算 CLV 指标、EWMA、名单状态（白/灰/黑）写入 `v2_monitor_metrics`
- 降级策略：触发 drift 后白→灰（禁止 Direction），保留 Risk/Diagnosis 输出

## 3. 代码隔离落地（目录与依赖边界）

### 3.1 目录结构

新增独立包：

- `src/market_script_v2/`
  - `engine.py`：对外入口（predictor 只依赖这个）
  - `models.py`：输出数据结构（dataclass/TypedDict）
  - `features/`：欧赔去水、AH 主线、序列特征、dispersion
  - `prototypes/`：原型与子类识别器
  - `decision/`：可靠度评分 + 跟随裁决器
  - `persistence/`：v2 表模型与写入（SQLAlchemy）
  - `monitoring/`：CLV、EWMA、白灰黑名单逻辑
  - `config.py`：阈值、窗口、regime 分层参数

### 3.2 隔离规则

- v2 不 import 旧 `micro_signals`、不读写 `data/rules/micro_signals.json`
- v2 表与旧表完全独立（表名前缀 `v2_`）
- predictor 侧只做“旁路调用 + 结果落库”，不让 v2 直接改动旧风控

## 4. 数据落地与表设计（SQLite / SQLAlchemy）

### 4.1 新增表（建议）

- `v2_odds_snapshot`：fixture_id, book_id, snapshot_time, odds_h/odds_d/odds_a, quality_flag
- `v2_ah_snapshot`：fixture_id, book_id, snapshot_time, ah_line, price_home/price_away, is_mainline, quality_flag
- `v2_script_output`：fixture_id, prediction_period, mode, engine_version, prototype, subclass, action_type, strength, direction_hint, why, veto_tags(JSON), created_at
- `v2_monitor_metrics`：subclass, league, regime, window_name, n, clv_rate, clv_magnitude, dispersion, ewma_clv, status(white/gray/black), updated_at

可选：

- `v2_execution_fills`：fixture_id, signal_time, observed_odds, tradable_odds, rejected_flag, latency_ms

### 4.2 与现有 DB 的集成方式

- 复用现有 `Database`（SQLAlchemy engine/session）
- 仅新增 v2 的 ORM Model 与写入方法
- 不修改旧表结构、不改旧查询逻辑

## 5. 采样脚本（关键）

### 5.1 采样目标

- 为 v2 提供足够的时间序列分辨率：识别速度、回撤、共振、收敛

### 5.2 采样频率建议

- T-24h ～ T-6h：每 2–4 小时
- T-6h ～ kickoff：每 30–60 分钟

### 5.3 最小实现

- 新增脚本 `scripts/v2_collect_market_snapshots.py`
- 输入：日期范围或今日比赛列表
- 输出：写入 `v2_odds_snapshot/v2_ah_snapshot`

运行示例：

- 采集今日比赛（默认今日）：`python scripts/v2_collect_market_snapshots.py`
- 采集指定日期（仅用于匹配当天列表）：`python scripts/v2_collect_market_snapshots.py 2026-05-13`

## 6. predictor 旁路接入（主界面不变）

### 6.1 接入点

在 `LLMPredictor.predict()` 里，靠近已有 micro_signals 计算处插入（不影响现有 `dynamic_rules`）：

- 位置参考：`micro_signals_text = self._analyze_micro_market_signals(...)` 之后
- 调用：`MarketScriptV2Engine.analyze(match_data, mode='shadow')`
- 行为：只落库，不改变 `dynamic_rules`，不改变 LLM prompt

### 6.2 配置开关

- `MARKET_SCRIPT_V2_MODE=shadow|observe|enforce`
- 默认 `shadow`

## 7. 对比评估（旧 vs 新）

### 7.1 评估数据集

- 与现有 `match_predictions` 对齐：同 fixture_id、同 prediction_period

### 7.2 指标

- CLV_rate + CLV_magnitude（统一口径）
- 分层稳定性：league/regime/强弱差
- 执行摩擦：slippage_rate/rejection_rate（可选）

补充：v2 每日复盘脚本（先做统计闭环，后续再接入 drift/名单自动化）

- `python scripts/v2_run_post_mortem.py 2026-05-13`
- 输出：`data/reports/v2_market_post_mortem_YYYY-MM-DD.md/json`

### 7.3 白名单准入

- 子类样本数达到门槛
- 样本外 CLV 指标区间下界优于基线
- drift 监控未触发

## 8. 灰度升级路线（不破坏旧系统）

1) Shadow：只记录与对比
2) Observe：报告追加实验诊断块（不改结论）
3) Enforce-Risk：只接管风控动作（双选/降置信/不下注提示）
4) Enforce-Dir：白名单 strong 子类才允许影响方向

## 9. 任务拆分（工程实施顺序）

### Task 1：新增 v2 模块骨架与数据模型

**Create:** `src/market_script_v2/**`

**Modify:** `src/db/database.py`（新增 v2 ORM + 写入方法）

**Test:** 新增最小单测覆盖 engine 输出结构与落库写入

### Task 2：实现采样脚本（写入 v2 快照表）

**Create:** `scripts/v2_collect_market_snapshots.py`

**Verify:** 连续运行一日，检查每场是否至少覆盖 3–5 个时间桶

### Task 3：实现 MVP 原型识别器（3 原型）

- info_shock
- head_fake
- cross_market_divergence

输出限制：只允许 strong info_shock Direction，其余 Risk/Diagnosis。

### Task 4：predictor 旁路接入（shadow 默认）

**Modify:** `src/llm/predictor.py`（插入旁路调用与落库）

**Verify:** Dashboard 预测输出完全一致；DB 多出 v2 输出记录

### Task 5：离线监控任务（CLV + drift + 名单）

**Create:** `scripts/v2_run_monitoring.py`

**Verify:** 能生成 `v2_monitor_metrics` 并在 drift 时降级

## 10. 验收标准

- 主界面功能与输出不变（shadow 下）
- v2 输出可在 DB 中完整追溯（fixture_id + period + version）
- 对比评估可跑通（至少输出 CLV 指标与分层统计）
- 白灰黑名单机制可自动降级，避免长期失效
