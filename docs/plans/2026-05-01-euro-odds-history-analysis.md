# 欧赔初赔vs临赔 + 赛果规律挖掘 方案

## 一、数据源

500.com 欧赔分析页 AJAX 接口：
```
GET https://odds.500.com/fenxi1/ouzhi.php?id={fixture_id}&ctype=1&start=0&r=1&guojia=1&chupan=1
```
- 返回 30 家博彩公司的初赔（第一行）和临赔（第二行）
- 需 `X-Requested-With: XMLHttpRequest` + 正确 `Referer`

## 二、已完成 (Step 1-3)

### ✅ Step 1：EuroOddsCrawler
- [euro_odds_crawler.py](file:///e:/zhangxuejun/football-prediction/src/crawler/euro_odds_crawler.py)
- `fetch_euro_odds(fixture_id)` → `list[dict]`，每项含 company, init_home/draw/away, live_home/draw/away

### ✅ Step 2：euro_odds_history 数据库表
- [database.py](file:///e:/zhangxuejun/football-prediction/src/db/database.py) 中的 `EuroOddsHistory` 模型
- 字段：fixture_id, company, init_home/draw/away, live_home/draw/away, actual_score, actual_result

### ✅ Step 3：批量拉取脚本
- [crawl_euro_odds_history.py](file:///e:/zhangxuejun/football-prediction/scripts/crawl_euro_odds_history.py)
- 用法：`python scripts/crawl_euro_odds_history.py 30`（从500.com直接拉取最近30天）
- 流程：JingcaiCrawler.fetch_history_matches → 逐场调用 EuroOddsCrawler → 存入 euro_odds_history

## 三、待完成 (Step 4-5)

### Step 4：规律分析脚本 → `scripts/analyze_euro_odds_patterns.py`
从 euro_odds_history 表读取数据，按以下维度交叉分析：

| 维度 | 变量 | 分级 |
|------|------|------|
| 赔率比 | init_ratio（高赔/低赔） | <1.15 / 1.15-1.25 / 1.25-1.40 / 1.40-2.0 / >2.0 |
| 资金方向 | 钱往初赔强队 vs 钱往初赔弱队 | 同向共识 / 反向背离 |
| 降幅 | 热门方赔率变化率 | <5% / 5-10% / 10-20% / >20% |

每个组合统计样本量和命中率，自动找出高危陷阱区间。

### Step 5：结论固化
- 将分析结论写入 `data/rules/micro_signals.json` 
- 更新 `rules.py` 的 `DYNAMIC_CHANGE_RULES`
