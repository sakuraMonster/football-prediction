# 欧亚盘口剧本固化：研究到落地实施方案（不依赖现有 micro_signals）

## 1. 背景与目标

### 1.1 背景
当前“盘口信号命中率低”的常见根因并非“盘口剧本不可固化”，而是固化方式落入以下陷阱：

- 数值过拟合：把具体小数赔率当作可复现规律
- 时序错位：用到了临场才出现的信息，却当作早盘信号
- 样本混杂：把不同联赛流动性、杯赛/联赛、末轮/常规轮等 regime 混在一起
- 单点对比：只看初盘与即时两点差，忽略时间序列形态（速度、回撤、共振）
- 单市场解释：只看亚盘或只看欧赔，忽略欧亚联动的一致/背离

### 1.2 目标
将“欧赔（1X2）+ 亚盘（AH）”的盘口行为，固化为一套可回测、可解释、可迭代的“剧本原型库 + 子类参数化模板”，用于：

- 识别盘口生成机制（信息冲击/风控/试盘/背离等），减少误判
- 给出动作类型：Direction / Risk / Diagnosis（先减少错误自信，再逐步升级方向）
- 以 CLV（Closing Line Value）为第一评价指标，再看赢盘/赛果提升，保证样本外稳定

### 1.3 范围与非目标

**范围**
- 以历史赔率时间序列为核心数据（欧赔、亚盘），结合必要的比赛语境标签做分层

**非目标**
- 不追求“读懂庄家意图”，只追求“可复现的市场行为模式 + 概率倾向”
- 不把每个细碎形态都固化成独立剧本（避免类别爆炸导致稀疏与过拟合）

## 2. 核心方法论：少原型 + 多参数

### 2.1 为什么“原型”不宜无限增长
- 盘口行为的底层生成机制是有限集合：信息定价、仓位风控、筹码引导、市场试探、临场纠偏
- 原型过多会导致样本稀疏与过拟合，样本外崩溃
- 更稳健的表达是：少数“生成机制原型”作为骨架，每个原型用参数化变体覆盖不同联赛/时间窗/语境

### 2.2 两层结构

- 第一层：8 个生成机制原型（跨联赛可复用）
- 第二层：每个原型 3–5 个可回测子类（总计约 30 个），用参数表达变体

## 3. 数据与清洗：先保证同一种数据

### 3.1 数据时间轴（最少 4 点，推荐 5 点）

- open（开盘后第一条可用）
- T-24h
- T-6h
- T-1h
- close（开赛前最后一条）

时间桶允许窗口（示例）：T-6h=±1h。

### 3.2 必备数据表（Schema）

#### 3.2.1 欧赔快照 odds_snapshot

- match_id
- book_id
- snapshot_time_utc
- odds_h / odds_d / odds_a（decimal）
- source
- quality_flag（0=正常，1=缺项，2=异常跳变，3=疑似口径错）

#### 3.2.2 亚盘快照 ah_snapshot（主线）

- match_id
- book_id
- snapshot_time_utc
- ah_line（-0.25/-0.5/-0.75/...）
- price_home / price_away（统一口径）
- is_mainline
- source
- quality_flag

#### 3.2.3 比赛语境 match_context

- match_id
- league_id / season
- kickoff_time_utc
- match_type（league/cup/playoff）
- round_index（可空）
- elo_home / elo_away（或任一强弱代理）
- popularity_home / popularity_away（热门代理，没有可空）
- table_lock_flag（提前锁定/垃圾时间，粗糙也可）
- derby_flag（可选）

#### 3.2.4 公司元数据 book_meta

- book_id
- book_tier（sharp/blunt/exchange/unknown）
- region

### 3.3 数据清洗硬标准

- 时间对齐：所有快照必须映射到固定时间桶
- 主线定义：同一时间点选择覆盖公司最多、价格最接近 50-50 的 AH 作为主线（可选增强：优先锐盘）
- 去水归一：欧赔必须转去水隐含概率再比较结构变化
- 异常过滤：单步变化过大且仅单公司发生的跳变标记异常
- 缺失降级：少于 3 个时间桶则只能做静态判断，禁止输出强方向

## 4. 特征工程：把数值转成可泛化标签

### 4.1 欧赔：去水概率 + 结构形状

对每个时间点 t：

- 去水概率：pH(t), pD(t), pA(t)
- 结构标签：
  - favorite_side(t)：主/客/无明显
  - draw_level(t)：低/中/高（按 pD 分桶）
  - strength_gap(t)：小/中/大（按 pFav - pDog 或 pFav/pDog 分桶）

变化标签（t2 相对 t1）：

- ΔpH, ΔpD, ΔpA 分桶：small/medium/large（推荐用训练集分位数自适应）
- shape_shift：主胜驱动 / 平局驱动 / 客胜驱动（谁的 |Δp| 最大）

### 4.2 亚盘：盘动 vs 水动、是否跨关键档位

- line_move：升盘/降盘/不变
- cross_key_number：是否跨过 0/0.25/0.5/0.75/1
- price_move_home/away：升/降/平稳（分桶）
- line_vs_price_ratio：盘动权重大 / 水动权重大

### 4.3 欧亚联动：同步与背离

- who_moves_first：欧先/亚先/同步/不确定（以首次超过阈值变化的时间桶判定）
- direction_coherence：同向/背离/弱相关
- multi_book_concordance：多家公司是否共振（投票或中位数聚合）

### 4.4 速度与回撤

- velocity_bucket：slow/fast（单位时间变化量分桶）
- reversal_flag：V 型/倒 V（先大幅变化后回撤超过阈值）

## 5. 生成机制原型库（第一层：8 个）

1) 信息冲击型（Info Shock / Sharp Reprice）
2) 仓位风控型（Risk Balancing / Shading）
3) 大众热度引导型（Public Pressure）
4) 试盘/假动作型（Head-fake / Market Test）
5) 欧亚背离型（Cross-market Divergence）
6) 关键档位管理型（Key-number Management）
7) 平局定价操盘型（Draw Shaping）
8) 临场纠偏型（Late Correction / Closing Efficiency）

## 6. 原型子类清单（第二层：约 30 个）

建议把每个子类固化为：

- subclass_id
- prototype
- detection_rules（由标签组成）
- default_action（Direction/Risk/Diagnosis）
- veto_tags（语境一票否决）
- evaluation_metrics（CLV_rate、lift 等）

子类示例（完整子类库在实现阶段落表维护）：

- A1 欧先动→亚后补（共振+跨档）
- A2 亚先跳档→欧跟随（steam-like）
- D1 早盘 V 型回撤
- E2 欧明显走向一边，AH 死扛关键档位
- G1 平局概率显著上升（pD↑）

## 7. 输出与动作体系：先减少错误自信

### 7.1 每场比赛输出字段（统一格式）

- prototype / subclass
- confidence_level（高/中/低）
- action_type：Direction / Risk / Diagnosis
- direction_hint（仅 Direction 时填：倾向强势方/弱势方/防平等）
- why（一句话解释：共振、速度、同步/背离、关键档位、平局驱动等）
- veto_tags（命中则强制降级）

### 7.2 语境一票否决（建议最少 5 个）

- cup_match_volatility
- low_liquidity_league
- final_round_or_lock
- expected_rotation
- derby_emotion

命中任意 veto_tag：禁止输出强方向，最多 Risk。

## 8. 方向裁决器：跟欧、跟亚、还是跟收盘

### 8.1 原则

- 先决定是否允许 Direction
- Direction 情况下：优先跟“可信度更高的一侧市场”；若欧亚一致且 close 可用，则跟收盘共识
- 欧亚背离时：默认降级 Risk；只有“可靠度差显著”才允许选边并降强度

### 8.2 可靠度分数（rel_euro / rel_ah）建议构成

- multi_book_concordance（共振）
- velocity（速度）
- data_quality（数据质量与时间桶完整性）
- book_tier（锐盘权重更高）

### 8.3 强度控制

- Strong：单挑（共振高、欧亚一致或冲突已明确解决、无 veto）
- Medium：双选/保守玩法（共振一般或背离选边）
- Weak：不下/仅提示风险（试盘回撤、公司分裂、数据缺失、命中 veto）

## 9. 评估方法：先 CLV 后赛果

### 9.1 指标顺序

1) CLV_rate：预测方向是否更容易拿到收盘优势
2) cover_rate / result_lift：赢盘/胜平负提升（样本外）
3) stability：按赛季/联赛分层的波动与一致性

### 9.2 样本外切分

- 按赛季切分（例如 2022–2024 找子类，2024–2025 验证）
- 按联赛流动性分层（主流 vs 小联赛）
- 按比赛类型分层（杯赛 vs 联赛、末轮）

## 10. 最小可行研究（MVP）路线

### 阶段 A：数据对齐与主线定义
- 完成时间桶映射、主线 AH 选择、欧赔去水概率

### 阶段 B：只做 3 个最强可区分原型
- info_shock
- head_fake
- cross_market_divergence

输出仅允许：强 info_shock 才 Direction，其余 Risk/Diagnosis。

### 阶段 C：先做 CLV 评估
- 用 CLV 过滤出样本外稳定的子类

### 阶段 D：逐步升级方向子类
- 从稳定子类中挑 2–3 个升级为 Direction，并为不同联赛分层参数

## 11. 风险与注意事项

- 低流动性联赛：close 不一定更有效，必须分层
- 公司口径差：欧亚背离可能是数据口径而非真实背离
- 语境突变：末轮/杯赛/德比/轮换会改变生成机制，必须 veto
- 指标误用：只看赛果会被噪声淹没，应先看 CLV

## 12. 交付物清单

- 数据表与清洗规则（schema + quality_flag）
- 特征标签定义（分桶采用分位数自适应）
- 原型识别器（prototype + subclass）
- 方向裁决器（可靠度、冲突处理、强度控制）
- 回测报告模板（CLV、lift、稳定性、分层）

## 13. 裁决器伪代码（研究实现参考）

### 13.1 欧赔去水概率

输入：odds_h, odds_d, odds_a（decimal）

输出：pH, pD, pA（去水隐含概率）

步骤：

- inv = [1/odds_h, 1/odds_d, 1/odds_a]
- s = sum(inv)
- pH = inv_h / s；pD = inv_d / s；pA = inv_a / s

### 13.2 时间桶映射

输入：kickoff_time_utc, snapshot_time_utc

输出：time_bucket ∈ {open, T-24h, T-6h, T-1h, close}

规则：

- 计算 dt_hours = (kickoff - snapshot_time) in hours
- 选择落入窗口的桶（例如 T-6h 窗口为 [5h, 7h]）
- open/close 用最早/最晚快照补位

### 13.3 主线 AH 选择（比赛级）

在同一 match_id + time_bucket + book_group 内：

1) 按 ah_line 分组，统计每个 ah_line 的公司覆盖数
2) 取覆盖数最大组
3) 若并列：取 |price_home - price_away| 最小组（更接近 50-50）
4) 若仍并列：按 book_tier 优先（sharp > blunt > unknown）

### 13.4 市场共识聚合（多公司→比赛级）

对每个 match_id、time_bucket：

- 欧侧：对各公司 pH,pD,pA 取中位数（或加权中位数）
- 亚侧：对主线 ah_line 取众数/中位数，对 price_home/away 取中位数

### 13.5 构造变化特征（序列）

以相邻桶 (t1, t2) 构造：

- ΔpH = pH(t2)-pH(t1)；ΔpD；ΔpA
- shape_shift = argmax(|ΔpH|, |ΔpD|, |ΔpA|)
- line_move = sign(ah_line(t2)-ah_line(t1))（注意让球正负方向口径）
- cross_key_number = 是否跨过 {0, 0.25, 0.5, 0.75, 1.0, ...}
- price_move_home = price_home(t2)-price_home(t1)
- velocity = max(|ΔpFav|, |Δline|, |Δprice|) / Δtime
- reversal_flag = 是否出现 “先 medium/large 变动后 medium/large 回撤”

### 13.6 原型识别（判别树）

输入：序列特征 + 数据质量 + company_concordance + context tags

输出：prototype、subclass、action_type、confidence、direction_hint（可空）

伪代码（概念级）：

- if insufficient_data: return Diagnosis
- if veto_tags hit: force action_type <= Risk
- if multi_book_concordance high and velocity fast:
  - if euro_ah coherent: prototype=info_shock
  - else: prototype=cross_market_divergence_candidate
- if reversal_flag: prototype=head_fake
- if line_move none and euro_move weak and price_move frequent: prototype=risk_balancing
- if draw_driven and |ΔpD| >= medium: prototype=draw_shaping
- if divergence persists across buckets: prototype=cross_market_divergence
- if close_correction strong: prototype=late_correction
- else prototype=public_pressure_or_drift

### 13.7 方向裁决（跟欧/亚/收盘）

输入：prototype/subclass、欧亚方向信号、rel_euro/rel_ah、coherence、close_available、veto

输出：final_dir、strength（strong/medium/weak）

建议逻辑：

- if action_type != Direction: final_dir = null
- else:
  - if coherent and close_available and rel_close_ok: final_dir = close_dir
  - else if coherent: final_dir = (rel_euro >= rel_ah) ? euro_dir : ah_dir
  - else:
    - if |rel_euro - rel_ah| >= threshold: final_dir = argmax(rel)
    - else: downgrade to Risk
- strength 由共振、速度、数据质量、veto 决定

## 14. 最小回测实验设计（2 周内出第一轮结论）

### 14.1 实验目标

- 验证：原型/子类是否能在样本外稳定提升 CLV_rate
- 其次：是否在赢盘/赛果上带来 lift（分层后）

### 14.2 数据切分

- 选择 2–3 个联赛（建议 1 个主流高流动性 + 1 个中等 + 1 个低流动性）
- 时间跨度：至少 2 个完整赛季
- 切分方式：用较早赛季做“子类阈值分位数 + 规则调参”，较新赛季做样本外验证

### 14.3 最小原型集（先做 3 个）

- info_shock（A 类）
- head_fake（D 类）
- cross_market_divergence（E 类）

输出限制：只有强条件 info_shock 才允许 Direction，其余一律 Risk/Diagnosis。

### 14.4 评价指标

- CLV_rate：在给出方向时，方向侧的收盘价格是否更有利
- CLV_magnitude：平均 CLV 幅度（只看率可能掩盖小优势）
- cover_rate / result_lift：赢盘/胜平负提升（按联赛、强弱分桶、语境分层）
- stability：赛季间波动与分层一致性

### 14.5 基线（必须对比）

- baseline_0：不使用盘口（随机/常识）
- baseline_1：只用欧赔单市场趋势
- baseline_2：只用亚盘单市场趋势
- baseline_3：简单跟收盘（如果你实战允许接近临场）

目标不是“绝对命中率”，而是证明：裁决器能在样本外稳定提高 CLV 与降低错误自信。

## 15. 进一步优化方案（从研究到稳定落地）

### 15.1 “先分型、后定向、再定强度”的产品化补充

将输出明确拆成三层（避免把所有信号都当方向信号）：

- 机制识别（prototype/subclass）：这场盘口更像信息、风控、试盘还是背离
- 动作类型（Direction/Risk/Diagnosis）：是否允许推方向
- 强度控制（strong/medium/weak）：单挑/双选/不下

落地建议：把“方向结论”从默认输出改成“稀缺输出”，只有在满足强条件时才允许 Direction。

### 15.2 增加“市场一致性”与“盘口分歧度”特征（提升解释力）

在欧赔与亚盘侧分别增加：

- dispersion：同一时间桶内不同公司的概率/水位分歧度（方差、IQR、极差）
- convergence：接近 close 时 dispersion 是否显著收敛

用途：

- 分歧度高时，强制降级为 Risk/Diagnosis
- 收敛度强时，提高 close_dir 的可信权重

### 15.3 引入“执行摩擦（slippage）”建模（从回测走向可交易）

赔率信号在实战中存在“成交价劣化”：

- 你观察到的赔率 ≠ 你能下注到的赔率（延迟、限额、跳水）

落地建议（回测摩擦模型）：

- 对每个 Direction 记录 signal_time_bucket，并对可下注赔率施加保守劣化：
  - 欧赔：将 odds 按不利方向调整 0.5%–2%（按联赛/公司分层）
  - AH：将价格向不利方向移动一个分位数（或固定 tick）
- 在压力测试中把摩擦放大到 1.5–2 倍，验证策略是否仍有 CLV 优势

### 15.4 参数鲁棒性：寻找“平台区间”，不要追“最优点”

对所有阈值（例如 threshold、共振判定、分桶分位点）做敏感性扫描：

- 在 0.8x / 1.0x / 1.2x 或 P55/P60/P65 等邻域中测试
- 目标是找到表现稳定的平台区间，而不是某个尖峰最优点

### 15.5 样本外与走步（walk-forward）验证

为了避免“赛季特异性过拟合”，建议采用：

- walk-forward：训练窗口（多个赛季）→ 验证窗口（下一赛季）滚动
- 赛季内分段：上半程/下半程、冬歇前后，做 regime 鲁棒性检查

### 15.6 负对照（negative control）与安慰剂测试（placebo）

为防止“看似有效但其实是巧合/数据泄漏”，强制做两类对照：

- 负对照：打乱 time_bucket 顺序或随机置换公司集合，若仍显著有效则说明方法有问题
- 安慰剂：把信号应用到不相关市场（例如把欧赔方向应用到随机比赛子集），应当无效

### 15.7 Regime 识别与自适应参数

将联赛/比赛类型显式作为 regime：

- 主流高流动性联赛：close 权重更高
- 低流动性联赛：dispersion 与异常过滤更严格，close 不默认更有效
- 杯赛/末轮：强制 veto 或降级，仅做风险提示

实现上将关键阈值按 regime 单独维护（而不是全局一套）。

## 16. 落地补充：工程化与数据流水线

### 16.1 数据抓取与存储增强

- 存储全量时间序列（至少 4–5 桶），不要只存初盘/即时/终盘
- 统一公司集合与口径：同 match_id 尽量使用同一批 book_id
- 保留每个时间桶的公司覆盖数与质量标记（quality_flag）
- 记录 close 的定义：kickoff 前最后一次采样时间与覆盖公司数

### 16.2 特征生成流水线

- 以比赛为单位聚合：中位数/加权中位数（按 book_tier）
- 生成并落表：prototype、subclass、rel_euro/rel_ah、action_type、strength
- 生成可复盘解释：why 字段必须由标签拼装，不透传原始盘赔文本

### 16.3 回测与监控自动化

- 每日/每周自动跑样本外评估：CLV_rate、CLV_magnitude、lift、stability
- 监控 drift：某个子类在近 N 场 CLV_rate 明显下滑则报警，进入降级名单
- 维护子类白名单/灰名单：只有白名单子类允许 Direction

## 17. 风控落地补充：从“预测”到“下注建议”

建议将下注建议拆成两类目标：

- 提升期望值：Direction + strong/medium
- 降低爆冷伤害：Risk（双选/走让球保守/降低置信）

强制规则：

- 当 action_type=Risk 或 strength=weak 时，禁止输出单挑结论
- 当 hit veto_tags 时，最多输出风险提示与备选路径

## 18. 迭代路线（从 2 周 MVP 到 6–8 周可用版本）

### 18.1 第 1–2 周（MVP）

- 打通数据对齐、去水、主线定义
- 只落地 3 原型（info_shock/head_fake/divergence）
- 以 CLV 为主指标，输出 Direction 稀缺化

### 18.2 第 3–4 周（扩展）

- 引入 dispersion/convergence 特征
- 子类扩展到约 12–15 个，并建立白名单
- 引入执行摩擦模型与阈值敏感性扫描

### 18.3 第 5–8 周（稳定与运营）

- 完成 walk-forward 与负对照/安慰剂测试
- 引入 drift 监控与自动降级
- 分 regime 维护参数与子类适用范围

## 19. 子类白名单/灰名单/黑名单机制（自动升级与降级）

### 19.1 目的

将“允许 Direction 的子类”做成可运营资产，持续追踪其样本外表现并自动淘汰失效子类，避免长期漂移导致命中率下滑。

### 19.2 名单定义

- 白名单（allow_direction）：允许输出 Direction（仍受 veto_tags 与 strength 控制）
- 灰名单（risk_only）：仅输出 Risk/Diagnosis，不允许单挑方向
- 黑名单（disabled）：不输出该子类（或仅作内部记录），避免污染解释与统计

### 19.3 升级/降级原则

所有升级与降级都基于样本外，且优先使用 CLV 指标（减少赛果噪声）。

最低样本门槛（建议）：

- promote_min_n：≥ 200（主流联赛可更高，低流动性可更低但更严格）
- demote_min_n：≥ 60（用于快速识别明显失效）

统计稳定性要求：

- 使用 Wilson 区间或贝叶斯后验对 CLV_rate 给出不确定性边界
- 当区间下界仍优于基线时才允许升级

### 19.4 升级规则（灰→白）

建议满足全部：

- rolling_CLV_rate（样本外）显著高于基线（同联赛/同强弱分桶）
- rolling_CLV_magnitude 为正且稳定
- stability：跨赛季/跨月份波动不过大（无单一月份贡献绝大多数优势）
- dispersion 处于可控范围（市场一致性足够）

### 19.5 降级规则（白→灰）

触发任一即可降级：

- 漂移预警：rolling_CLV_rate 连续 K 个窗口低于阈值
- 断崖预警：EWMA_CLV 出现显著下穿（相对历史均值）
- 异常分歧：dispersion 长期抬升（市场不再一致），导致方向难以执行

### 19.6 黑名单规则（灰/白→黑）

满足任一：

- 负对照/安慰剂测试显示疑似数据泄漏或伪规律
- 样本外长期负 CLV_magnitude（不仅仅是 rate 下降）
- 强依赖单一联赛/单一赛季且迁移失败

## 20. Drift 监控指标（CLV 优先的可执行定义）

### 20.1 核心监控指标

对每个 subclass（按 league_id 与 regime 分层）每日/每周计算：

- N：窗口内样本数
- CLV_rate：方向侧在 close 上更有利的比例
- CLV_magnitude：平均 CLV 幅度（建议以去水概率差或对数赔率差表示）
- hit_rate（可选）：赢盘/赛果命中，仅作参考
- dispersion：公司分歧度（IQR/方差）
- convergence：close 前是否收敛（dispersion 是否下降）

### 20.2 窗口设计

建议同时维护三种窗口：

- short_window：最近 50–100 场（快速发现断崖）
- mid_window：最近 200–400 场（评估稳定性）
- long_window：最近 800+ 场（基准与控制图参考）

### 20.3 EWMA 与控制图式预警（推荐）

- EWMA_CLV = α * CLV_today + (1-α) * EWMA_yesterday
- 预警条件示例：
  - EWMA_CLV 低于长期均值 - 2σ 持续 M 次
  - short_window 的 CLV_rate 低于 mid_window 的下界

### 20.4 基线与分层

所有阈值必须分层定义：

- baseline_by_league（主流/非主流不同）
- baseline_by_strength_gap（强弱差不同）
- baseline_by_match_type（杯赛/联赛不同）

## 21. 自动降级与人工复核流程（运营闭环）

### 21.1 自动动作

- 预警触发后：子类从白→灰（立刻禁止 Direction）
- 保留解释输出：仍输出 Risk/Diagnosis，避免用户体验断崖

### 21.2 复核清单

对降级子类进行快速定位：

- 数据问题：公司集合变化、时间桶缺失、口径切换
- regime 变化：联赛风格变化、规则变化、赛程压缩导致轮换普遍化
- 执行问题：可下注价与观测价偏差增大（摩擦上升）

### 21.3 再训练与回归

- 若判定为数据/执行问题：先修数据再回测
- 若判定为真实漂移：重新做 walk-forward，更新阈值与子类边界
- 通过升级规则后再灰→白

## 22. 子类配置模板（便于工程落表）

建议维护一个配置文件（JSON/YAML 任一），每个子类包含：

- subclass_id
- prototype
- detection_rules（标签规则集合）
- default_action
- allow_direction（bool）
- veto_tags
- thresholds（分位数/阈值按 regime 分层）
- monitoring（窗口大小、预警阈值、降级策略）

目标：把“研究结论”变成可版本化、可回滚、可审计的配置资产。

## 23. CLV_magnitude 口径统一（关键落地补充）

### 23.1 为什么必须统一 CLV 口径

- 只用 CLV_rate（收盘是否更有利）容易忽略“优势大小”
- 不同市场（欧赔/亚盘）与不同赔率口径（decimal/香港盘）直接相减不可比
- 统一到“概率空间”或“对数赔率空间”，才能跨联赛/跨公司稳定比较

### 23.2 推荐两种 CLV_magnitude 定义

#### 方案 A：概率差（推荐用于欧赔）

- 使用去水隐含概率 p(t)
- 对选择方向（例如强势方）定义：
  - CLV_prob = p_close - p_signal

优点：可解释、可跨公司归一。

#### 方案 B：log-odds 差（推荐用于统一刻度）

- 对二元事件（例如强势方方向）定义：
  - logit(p) = ln(p / (1-p))
  - CLV_logit = logit(p_close) - logit(p_signal)

优点：对极端概率更敏感，适合做控制图与 EWMA。

### 23.3 亚盘（AH）侧的 CLV 口径

AH 的“方向”不是单一路径概率，建议用以下替代方案之一：

- 将 AH 价格转换为隐含概率（按盘口公司口径与返水模型统一），再计算 CLV_prob/CLV_logit
- 或在同一主线盘口下，用价格变化作为 proxy：
  - CLV_price = price_close - price_signal（对不利方向取负）

注意：若跨档位，必须先把事件重新定义为“强势方穿盘”在新档位下的等价概率，否则直接比较会失真。

### 23.4 信号时间点定义

- signal_time_bucket 必须落表（open/T-24/T-6/T-1/close）
- 若信号发生在 bucket 内，使用该 bucket 内最后一次快照作为 signal_price（更贴近可执行）

## 24. 观测价 vs 成交价：执行摩擦（Fill Slippage）监控

### 24.1 需要新增的数据字段（如有能力采集）

- observed_odds：系统观测到的赔率（用于识别与回测）
- tradable_odds：实际可下注赔率（成交或下单回执）
- rejected_flag：是否拒单/限额
- latency_ms：从观测到下单的延迟

### 24.2 摩擦指标

- slippage = tradable_odds - observed_odds（按方向统一符号）
- slippage_rate：slippage 超过阈值的比例
- rejection_rate：拒单/限额比例

### 24.3 摩擦对策略的硬约束

- 若某子类的 slippage_rate 或 rejection_rate 超阈值：即使 CLV 在观测价上有效，也应降级（白→灰）
- 回测时对所有 Direction 强制加入保守摩擦（并做 1.5–2 倍压力测试）

## 25. 避免常见回测陷阱（Bias Checklist）

### 25.1 Look-ahead bias

- 禁止使用 close 之后的信息构建 signal
- 语境标签（锁定名次/轮换预期）必须来自比赛前可获得数据

### 25.2 Survivorship / selection bias

- 不允许只挑“看起来像诱盘”的样本，必须覆盖所有满足检测条件的比赛

### 25.3 多重检验与过拟合

- 子类越多，虚假显著性越高
- 对子类的显著性检验需做 FDR/Bonferroni 等保守修正，或采用贝叶斯层级模型

### 25.4 执行可行性偏差

- 若无法在 signal_time_bucket 执行到接近观测价，策略不可落地

## 26. 进一步增强：层级贝叶斯与可信度融合（可选）

当你需要在多联赛、多子类上统一估计“真实有效性”，建议：

- 使用层级贝叶斯对 CLV_rate 做后验估计：
  - 子类层 → 联赛层 → 全局层
- 优点：
  - 小样本子类不会被偶然好运误升白
  - 大样本子类能更快收敛到真实优势

落地输出：

- posterior_mean_CLV_rate
- posterior_lower_bound（用于升级门槛）
