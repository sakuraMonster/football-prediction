# 足球预测系统 (Football Prediction System)

这是一个基于数据爬取与大语言模型 (LLM) 分析的足球赛事（竞彩）预测系统。它能够自动拉取每天的竞彩赛事数据、外部基本面和盘口赔率数据，并通过精心设计的 Prompt 交由大模型进行推理分析，最后输出胜平负预测、比分参考和信心指数。

## 核心架构

1. **数据采集层 (Data Fetcher)**:
   - 抓取中国体彩官网（竞彩）每日赛程及官方赔率。
   - 接入第三方体育数据 API (如 API-Football, 或爬取懂球帝等)，获取球队基本面数据（近期战绩、交锋、伤停等）和主流机构（澳门、Bet365等）的初盘与即时盘赔数据。
2. **数据处理与融合层 (Data Processor)**:
   - 清洗数据，解决体彩与第三方数据源之间“队名不一致”的问题（队名映射与对齐）。
   - 将零散的数据组装为结构化的字典 / JSON。
3. **大语言模型预测层 (LLM Engine)**:
   - 结合专业足球分析师思维框架，将数据填入 Prompt 模板。
   - 调用大模型（如 GPT-4o, DeepSeek, Claude 等）API 进行深度分析和推理。
   - 解析模型输出结果。
4. **存储与复盘层 (Storage & Backtesting)**:
   - 将预测结果和真实赛果存储至 SQLite 数据库。
   - 定期复盘，计算命中率并优化 Prompt。
5. **展示与推送层 (UI & Notification)**:
   - （可选）通过 Streamlit 提供 Web 界面展示预测面板。
   - （可选）定时推送到微信、钉钉或 Telegram 群组。

## 目录结构

```text
football-prediction/
├── config/             # 配置文件 (API keys, 数据库配置等)
├── data/               # 本地数据缓存 (如 JSON 缓存)
├── logs/               # 日志文件夹
├── src/                # 源代码目录
│   ├── crawler/        # 爬虫与 API 数据抓取模块
│   ├── processor/      # 数据清洗、特征工程、队名对齐
│   ├── llm/            # LLM API 调用与 Prompt 模板管理
│   ├── db/             # 数据库操作 (SQLite)
│   └── main.py         # 主程序入口
├── tests/              # 单元测试
├── requirements.txt    # 项目依赖
└── README.md           # 项目文档
```
