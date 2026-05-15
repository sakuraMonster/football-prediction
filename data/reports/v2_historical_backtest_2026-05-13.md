# v2 历史回测（欧赔 init/live 合成 3 桶）

- prediction_bias 模式：B
- 数据源：`data\football.db` / `euro_odds_history`
- 赛程过滤：since=-，until=-，limit=300
- 最少公司数：5
- 总 fixture：60，可评估：60，跳过：0
- 有亚盘快照（来自 match_predictions.raw_data）：32
- baseline（open favored 胜率）：46.6%

- v2 预测偏向覆盖率：78.3%（prediction_bias 非空）
- v2 平局覆盖率：70.0%（prediction_bias 含“平”）

## 子类汇总（按样本量排序）

| subclass | prototype | action | n | CLV+率 | 平均CLV_prob | favored胜率 | vs baseline |
|---|---|---|---:|---:|---:|---:|---:|
| risk_balancing_flat_drift | risk_balancing | Risk | 21 | 19.0% | -0.0175 | 55.0% | 8.4% |
| late_correction_key_cross | late_correction | Risk | 9 | 37.5% | -0.0256 | 25.0% | -21.6% |
| public_pressure_popular_tax | public_pressure | Risk | 9 | 0.0% | -0.0511 | 55.6% | 9.0% |
| drift | risk_balancing | Risk | 8 | 100.0% | 0.0122 | 37.5% | -9.1% |
| info_shock_mvp | info_shock | Risk | 5 | 100.0% | 0.0471 | 40.0% | -6.6% |
| divergence_euro_vs_ah | cross_market_divergence | Risk | 4 | 50.0% | -0.0114 | 50.0% | 3.4% |
| risk_balancing_price_only | risk_balancing | Diagnosis | 4 | 0.0% | -0.0160 | 50.0% | 3.4% |

## 子类汇总（按平均CLV_prob排序，n>=20）

| subclass | prototype | action | n | CLV+率 | 平均CLV_prob | favored胜率 | vs baseline |
|---|---|---|---:|---:|---:|---:|---:|
| risk_balancing_flat_drift | risk_balancing | Risk | 21 | 19.0% | -0.0175 | 55.0% | 8.4% |

## Risk 子类：降低热门胜率效果（baseline - favored胜率，n>=20）

| subclass | prototype | n | 风险效果 | favored胜率 | baseline |
|---|---|---:|---:|---:|---:|
| risk_balancing_flat_drift | risk_balancing | 21 | -8.4% | 55.0% | 46.6% |
