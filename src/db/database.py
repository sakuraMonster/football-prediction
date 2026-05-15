from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from typing import Any, Dict, List, Optional
import os
import re
from datetime import datetime
from datetime import date
from loguru import logger

Base = declarative_base()


def _parse_match_time_value(value):
    """兼容无秒/有秒/ISO 字符串的比赛时间解析。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_actual_result_from_score(score):
    """根据比分文本推导实际胜平负。"""
    if not score:
        return None

    match = re.search(r'(\d+)\s*[:：-]\s*(\d+)', str(score))
    if not match:
        return None

    home_score = int(match.group(1))
    away_score = int(match.group(2))
    if home_score > away_score:
        return "胜"
    if home_score < away_score:
        return "负"
    return "平"


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[str(k)] = _json_safe(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    if isinstance(value, set):
        return [_json_safe(x) for x in sorted(list(value), key=lambda x: str(x))]
    try:
        import json as _json

        _json.dumps(value)
        return value
    except Exception:
        return str(value)

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), default='vip') # admin, editor, vip
    valid_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class MatchPrediction(Base):
    __tablename__ = 'match_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)  # 移除unique约束，允许多个时间段记录
    match_num = Column(String(50))
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 时间段标识：pre_24h, pre_12h, final
    prediction_period = Column(String(20), default='pre_24h')
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    # 半全场(平胜/平负) 专项预测结果
    htft_prediction_text = Column(Text, nullable=True)
    
    # 主模型从预测报告中解析出的竞彩推荐（不让球）
    predicted_result = Column(String(100), nullable=True)
    confidence = Column(Integer, nullable=True) # 1-5星
    
    # 实际赛果
    actual_result = Column(String(50), nullable=True)
    actual_score = Column(String(50), nullable=True)
    actual_bqc = Column(String(20), nullable=True) # 半全场赛果 (e.g. 1-3)
    is_correct = Column(Boolean, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class BasketballPrediction(Base):
    __tablename__ = 'basketball_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    match_num = Column(String(50))
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    # 实际赛果
    actual_score = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class SfcPrediction(Base):
    __tablename__ = 'sfc_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_num = Column(String(50), index=True) # 期号
    fixture_id = Column(String(50))
    match_num = Column(String(50)) # 例如 胜负彩_1
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class DailyParlays(Base):
    """用于存储每日生成的串子单方案"""
    __tablename__ = 'daily_parlays'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    # 保存方案生成的日期 (格式: YYYY-MM-DD)
    target_date = Column(String(20), index=True)
    # 最新的方案内容
    current_parlay = Column(Text)
    # 上一次的方案内容（用于对比）
    previous_parlay = Column(Text, nullable=True)
    # AI对两次方案的对比分析结果
    comparison_text = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class DailyReview(Base):
    """用于存储每日复盘结果"""
    __tablename__ = 'daily_reviews'

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_date = Column(String(20), index=True, unique=True)
    review_content = Column(Text) # LLM的复盘总结
    htft_review_content = Column(Text, nullable=True) # 半全场专项复盘总结
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class EuroOddsHistory(Base):
    """欧赔初赔vs临赔历史数据，用于赔率变化规律分析"""
    __tablename__ = 'euro_odds_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    match_num = Column(String(50), nullable=True)
    league = Column(String(100), nullable=True)
    home_team = Column(String(100), nullable=True)
    away_team = Column(String(100), nullable=True)
    match_time = Column(DateTime, nullable=True)
    company = Column(String(100), nullable=True)  # 博彩公司名称
    init_home = Column(String(20), nullable=True)  # 初赔主胜
    init_draw = Column(String(20), nullable=True)  # 初赔平局
    init_away = Column(String(20), nullable=True)  # 初赔客胜
    live_home = Column(String(20), nullable=True)  # 临赔主胜
    live_draw = Column(String(20), nullable=True)  # 临赔平局
    live_away = Column(String(20), nullable=True)  # 临赔客胜
    actual_score = Column(String(50), nullable=True)  # 实际比分
    actual_result = Column(String(20), nullable=True)  # 胜/平/负
    data_source = Column(String(50), default='500.com')  # 数据来源
    created_at = Column(DateTime, default=datetime.now)


class V2OddsSnapshot(Base):
    __tablename__ = "v2_odds_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    book_id = Column(String(50), index=True)
    snapshot_time = Column(DateTime, index=True)
    odds_h = Column(String(20), nullable=True)
    odds_d = Column(String(20), nullable=True)
    odds_a = Column(String(20), nullable=True)
    quality_flag = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class V2AHSnapshot(Base):
    __tablename__ = "v2_ah_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    book_id = Column(String(50), index=True)
    snapshot_time = Column(DateTime, index=True)
    ah_line = Column(String(20), nullable=True)
    price_home = Column(String(20), nullable=True)
    price_away = Column(String(20), nullable=True)
    is_mainline = Column(Boolean, default=False)
    quality_flag = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class V2ScriptOutput(Base):
    __tablename__ = "v2_script_output"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    prediction_period = Column(String(20), default="final", index=True)
    league = Column(String(50), nullable=True, index=True)
    mode = Column(String(20), default="shadow")
    engine_version = Column(String(20), default="0.0.0")
    prototype = Column(String(50), nullable=True)
    subclass = Column(String(80), nullable=True)
    action_type = Column(String(20), nullable=True)
    strength = Column(String(20), nullable=True)
    prediction_bias = Column(String(50), nullable=True)
    direction_hint = Column(String(50), nullable=True)
    why = Column(Text, nullable=True)
    veto_tags = Column(JSON, nullable=True)
    signal_bucket = Column(String(20), nullable=True)
    clv_prob = Column(Float, nullable=True)
    clv_logit = Column(Float, nullable=True)
    dispersion = Column(Float, nullable=True)
    nspf_top1 = Column(String(20), nullable=True)
    nspf_cover = Column(String(20), nullable=True)
    nspf_confidence = Column(Integer, nullable=True)
    nspf_scores = Column(JSON, nullable=True)
    decision_reason = Column(Text, nullable=True)
    feedback_tag = Column(String(40), nullable=True)
    upset_alert_level = Column(String(20), nullable=True)
    upset_alert_score = Column(Integer, nullable=True)
    upset_direction = Column(String(40), nullable=True)
    upset_reasons = Column(JSON, nullable=True)
    upset_guard_pick = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class V2MonitorMetric(Base):
    __tablename__ = "v2_monitor_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subclass = Column(String(80), index=True)
    league = Column(String(50), index=True)
    regime = Column(String(40), index=True, default="default")
    window_name = Column(String(20), index=True)
    n = Column(Integer, default=0)
    clv_rate = Column(Float, nullable=True)
    clv_magnitude = Column(Float, nullable=True)
    dispersion = Column(Float, nullable=True)
    ewma_clv = Column(Float, nullable=True)
    status = Column(String(10), default="gray")
    updated_at = Column(DateTime, default=datetime.now, index=True)


class V2BacktestRun(Base):
    __tablename__ = "v2_backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_tag = Column(String(40), index=True, default="historical")
    since = Column(String(20), nullable=True)
    until = Column(String(20), nullable=True)
    limit = Column(Integer, nullable=True)
    min_books = Column(Integer, default=5)
    total_fixtures = Column(Integer, default=0)
    evaluated = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    fixtures_with_ah = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, index=True)


class V2BacktestRow(Base):
    __tablename__ = "v2_backtest_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, index=True)
    fixture_id = Column(String(50), index=True)
    league = Column(String(100), nullable=True, index=True)
    kickoff = Column(DateTime, nullable=True, index=True)
    prototype = Column(String(50), nullable=True, index=True)
    subclass = Column(String(80), nullable=True, index=True)
    action_type = Column(String(20), nullable=True)
    strength = Column(String(20), nullable=True)
    prediction_bias = Column(String(20), nullable=True)
    signal_bucket = Column(String(20), nullable=True)
    clv_prob = Column(Float, nullable=True)
    clv_logit = Column(Float, nullable=True)
    dispersion = Column(Float, nullable=True)
    euro_favored_prob_delta = Column(Float, nullable=True)
    draw_prob_delta = Column(Float, nullable=True)
    favored_side = Column(String(10), nullable=True)
    actual_result = Column(String(20), nullable=True)
    favored_win = Column(Boolean, nullable=True)
    why = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class V2DailyFixture(Base):
    __tablename__ = "v2_daily_fixtures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    window_tag = Column(String(40), index=True)
    window_start = Column(DateTime, index=True)
    window_end = Column(DateTime, index=True)
    fixture_id = Column(String(50), index=True)
    match_num = Column(String(50), nullable=True)
    league = Column(String(100), nullable=True)
    home_team = Column(String(100), nullable=True)
    away_team = Column(String(100), nullable=True)
    kickoff_time = Column(DateTime, nullable=True, index=True)
    source = Column(String(40), default="jingcai")
    created_at = Column(DateTime, default=datetime.now, index=True)


class V2DailyReport(Base):
    __tablename__ = "v2_daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_date = Column(String(20), index=True, unique=True)
    window_start = Column(DateTime, nullable=True, index=True)
    window_end = Column(DateTime, nullable=True, index=True)
    report_path = Column(String(255), nullable=True)
    total_matches = Column(Integer, default=0)
    prog_cover_acc = Column(Float, nullable=True)
    prog_top1_acc = Column(Float, nullable=True)
    final_cover_acc = Column(Float, nullable=True)
    final_top1_acc = Column(Float, nullable=True)
    baseline_acc = Column(Float, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    markdown_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, index=True)


class V2DailyReportRow(Base):
    __tablename__ = "v2_daily_report_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_date = Column(String(20), index=True)
    fixture_id = Column(String(50), index=True)
    match_num = Column(String(50), nullable=True)
    league = Column(String(100), nullable=True, index=True)
    home_team = Column(String(100), nullable=True)
    away_team = Column(String(100), nullable=True)
    kickoff = Column(DateTime, nullable=True, index=True)
    actual_result = Column(String(20), nullable=True)
    prog_cover = Column(String(20), nullable=True)
    prog_top1 = Column(String(20), nullable=True)
    final_cover = Column(String(20), nullable=True)
    final_top1 = Column(String(20), nullable=True)
    baseline = Column(String(20), nullable=True)
    prog_cover_hit = Column(Boolean, nullable=True)
    prog_top1_hit = Column(Boolean, nullable=True)
    final_cover_hit = Column(Boolean, nullable=True)
    final_top1_hit = Column(Boolean, nullable=True)
    baseline_hit = Column(Boolean, nullable=True)
    subclass = Column(String(80), nullable=True, index=True)
    prototype = Column(String(50), nullable=True)
    prediction_bias = Column(String(50), nullable=True, index=True)
    feedback_tag = Column(String(40), nullable=True)
    prog_confidence = Column(Integer, nullable=True)
    league_subclass = Column(String(160), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class Database:
    def __init__(self, db_url=None):
        if db_url is None:
            # 动态计算绝对路径，确保无论从哪个目录启动，都能找到正确的 data/football.db
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "football.db")
            db_url = f"sqlite:///{db_path}"
            
        # 确保目录存在
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self._ensure_match_predictions_columns()
        self._ensure_v2_columns()
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def _ensure_v2_columns(self):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            def _table_exists(name: str) -> bool:
                r = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                    {"name": name},
                ).fetchone()
                return r is not None

            def _cols(name: str):
                rows = conn.execute(text(f"PRAGMA table_info({name})")).fetchall()
                return {str(r[1]) for r in rows}

            def _add_col(table: str, col: str, ddl: str):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))

            if _table_exists("v2_script_output"):
                cols = _cols("v2_script_output")
                if "league" not in cols:
                    _add_col("v2_script_output", "league", "VARCHAR(50)")
                if "signal_bucket" not in cols:
                    _add_col("v2_script_output", "signal_bucket", "VARCHAR(20)")
                if "clv_prob" not in cols:
                    _add_col("v2_script_output", "clv_prob", "FLOAT")
                if "clv_logit" not in cols:
                    _add_col("v2_script_output", "clv_logit", "FLOAT")
                if "dispersion" not in cols:
                    _add_col("v2_script_output", "dispersion", "FLOAT")
                if "prediction_bias" not in cols:
                    _add_col("v2_script_output", "prediction_bias", "VARCHAR(50)")
                if "nspf_top1" not in cols:
                    _add_col("v2_script_output", "nspf_top1", "VARCHAR(20)")
                if "nspf_cover" not in cols:
                    _add_col("v2_script_output", "nspf_cover", "VARCHAR(20)")
                if "nspf_confidence" not in cols:
                    _add_col("v2_script_output", "nspf_confidence", "INTEGER")
                if "nspf_scores" not in cols:
                    _add_col("v2_script_output", "nspf_scores", "JSON")
                if "decision_reason" not in cols:
                    _add_col("v2_script_output", "decision_reason", "TEXT")
                if "feedback_tag" not in cols:
                    _add_col("v2_script_output", "feedback_tag", "VARCHAR(40)")
                if "upset_alert_level" not in cols:
                    _add_col("v2_script_output", "upset_alert_level", "VARCHAR(20)")
                if "upset_alert_score" not in cols:
                    _add_col("v2_script_output", "upset_alert_score", "INTEGER")
                if "upset_direction" not in cols:
                    _add_col("v2_script_output", "upset_direction", "VARCHAR(40)")
                if "upset_reasons" not in cols:
                    _add_col("v2_script_output", "upset_reasons", "JSON")
                if "upset_guard_pick" not in cols:
                    _add_col("v2_script_output", "upset_guard_pick", "VARCHAR(20)")

            if _table_exists("v2_monitor_metrics"):
                cols = _cols("v2_monitor_metrics")
                expected = {
                    ("subclass", "VARCHAR(80)"),
                    ("league", "VARCHAR(50)"),
                    ("regime", "VARCHAR(40)"),
                    ("window_name", "VARCHAR(20)"),
                    ("n", "INTEGER"),
                    ("clv_rate", "FLOAT"),
                    ("clv_magnitude", "FLOAT"),
                    ("dispersion", "FLOAT"),
                    ("ewma_clv", "FLOAT"),
                    ("status", "VARCHAR(10)"),
                    ("updated_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_monitor_metrics", col, ddl)

            if _table_exists("v2_backtest_runs"):
                cols = _cols("v2_backtest_runs")
                expected = {
                    ("run_tag", "VARCHAR(40)"),
                    ("since", "VARCHAR(20)"),
                    ("until", "VARCHAR(20)"),
                    ("limit", "INTEGER"),
                    ("min_books", "INTEGER"),
                    ("total_fixtures", "INTEGER"),
                    ("evaluated", "INTEGER"),
                    ("skipped", "INTEGER"),
                    ("fixtures_with_ah", "INTEGER"),
                    ("created_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_backtest_runs", col, ddl)

            if _table_exists("v2_backtest_rows"):
                cols = _cols("v2_backtest_rows")
                expected = {
                    ("run_id", "INTEGER"),
                    ("fixture_id", "VARCHAR(50)"),
                    ("league", "VARCHAR(100)"),
                    ("kickoff", "DATETIME"),
                    ("prototype", "VARCHAR(50)"),
                    ("subclass", "VARCHAR(80)"),
                    ("action_type", "VARCHAR(20)"),
                    ("strength", "VARCHAR(20)"),
                    ("prediction_bias", "VARCHAR(20)"),
                    ("signal_bucket", "VARCHAR(20)"),
                    ("clv_prob", "FLOAT"),
                    ("clv_logit", "FLOAT"),
                    ("dispersion", "FLOAT"),
                    ("euro_favored_prob_delta", "FLOAT"),
                    ("draw_prob_delta", "FLOAT"),
                    ("favored_side", "VARCHAR(10)"),
                    ("actual_result", "VARCHAR(20)"),
                    ("favored_win", "BOOLEAN"),
                    ("why", "TEXT"),
                    ("created_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_backtest_rows", col, ddl)

            if _table_exists("v2_daily_fixtures"):
                cols = _cols("v2_daily_fixtures")
                expected = {
                    ("window_tag", "VARCHAR(40)"),
                    ("window_start", "DATETIME"),
                    ("window_end", "DATETIME"),
                    ("fixture_id", "VARCHAR(50)"),
                    ("match_num", "VARCHAR(50)"),
                    ("league", "VARCHAR(100)"),
                    ("home_team", "VARCHAR(100)"),
                    ("away_team", "VARCHAR(100)"),
                    ("kickoff_time", "DATETIME"),
                    ("source", "VARCHAR(40)"),
                    ("created_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_daily_fixtures", col, ddl)

            if _table_exists("v2_daily_reports"):
                cols = _cols("v2_daily_reports")
                expected = {
                    ("target_date", "VARCHAR(20)"),
                    ("window_start", "DATETIME"),
                    ("window_end", "DATETIME"),
                    ("report_path", "VARCHAR(255)"),
                    ("total_matches", "INTEGER"),
                    ("prog_cover_acc", "FLOAT"),
                    ("prog_top1_acc", "FLOAT"),
                    ("final_cover_acc", "FLOAT"),
                    ("final_top1_acc", "FLOAT"),
                    ("baseline_acc", "FLOAT"),
                    ("metrics_json", "JSON"),
                    ("markdown_content", "TEXT"),
                    ("created_at", "DATETIME"),
                    ("updated_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_daily_reports", col, ddl)

            if _table_exists("v2_daily_report_rows"):
                cols = _cols("v2_daily_report_rows")
                expected = {
                    ("target_date", "VARCHAR(20)"),
                    ("fixture_id", "VARCHAR(50)"),
                    ("match_num", "VARCHAR(50)"),
                    ("league", "VARCHAR(100)"),
                    ("home_team", "VARCHAR(100)"),
                    ("away_team", "VARCHAR(100)"),
                    ("kickoff", "DATETIME"),
                    ("actual_result", "VARCHAR(20)"),
                    ("prog_cover", "VARCHAR(20)"),
                    ("prog_top1", "VARCHAR(20)"),
                    ("final_cover", "VARCHAR(20)"),
                    ("final_top1", "VARCHAR(20)"),
                    ("baseline", "VARCHAR(20)"),
                    ("prog_cover_hit", "BOOLEAN"),
                    ("prog_top1_hit", "BOOLEAN"),
                    ("final_cover_hit", "BOOLEAN"),
                    ("final_top1_hit", "BOOLEAN"),
                    ("baseline_hit", "BOOLEAN"),
                    ("subclass", "VARCHAR(80)"),
                    ("prototype", "VARCHAR(50)"),
                    ("prediction_bias", "VARCHAR(50)"),
                    ("feedback_tag", "VARCHAR(40)"),
                    ("prog_confidence", "INTEGER"),
                    ("league_subclass", "VARCHAR(160)"),
                    ("created_at", "DATETIME"),
                }
                for col, ddl in expected:
                    if col not in cols:
                        _add_col("v2_daily_report_rows", col, ddl)

    def save_v2_script_output(self, output):
        data = getattr(output, "to_record", None)
        if callable(data):
            record = data()
        elif isinstance(output, dict):
            record = output
        else:
            record = {}

        fixture_id = str(record.get("fixture_id") or "").strip()
        if not fixture_id:
            return None

        row = V2ScriptOutput(
            fixture_id=fixture_id,
            prediction_period=str(record.get("prediction_period") or "final"),
            league=str(record.get("league") or ""),
            mode=str(record.get("mode") or "shadow"),
            engine_version=str(record.get("engine_version") or "0.0.0"),
            prototype=str(record.get("prototype") or ""),
            subclass=str(record.get("subclass") or ""),
            action_type=str(record.get("action_type") or ""),
            strength=str(record.get("strength") or ""),
            prediction_bias=str(record.get("prediction_bias") or ""),
            direction_hint=str(record.get("direction_hint") or ""),
            why=str(record.get("why") or ""),
            veto_tags=record.get("veto_tags") or [],
            signal_bucket=str(record.get("signal_bucket") or ""),
            clv_prob=record.get("clv_prob"),
            clv_logit=record.get("clv_logit"),
            dispersion=record.get("dispersion"),
            nspf_top1=str(record.get("nspf_top1") or ""),
            nspf_cover=str(record.get("nspf_cover") or ""),
            nspf_confidence=record.get("nspf_confidence"),
            nspf_scores=_json_safe(record.get("nspf_scores")),
            decision_reason=str(record.get("decision_reason") or ""),
            feedback_tag=str(record.get("feedback_tag") or ""),
            upset_alert_level=str(record.get("upset_alert_level") or ""),
            upset_alert_score=record.get("upset_alert_score"),
            upset_direction=str(record.get("upset_direction") or ""),
            upset_reasons=_json_safe(record.get("upset_reasons") or []),
            upset_guard_pick=str(record.get("upset_guard_pick") or ""),
            created_at=record.get("created_at") or datetime.now(),
        )

        self.session.add(row)
        self.session.commit()
        return row.id

    def upsert_v2_monitor_metric(
        self,
        *,
        subclass: str,
        league: str,
        regime: str,
        window_name: str,
        n: int,
        clv_rate: Optional[float],
        clv_magnitude: Optional[float],
        dispersion: Optional[float],
        ewma_clv: Optional[float],
        status: str,
    ):
        subclass = str(subclass or "").strip()
        league = str(league or "").strip()
        regime = str(regime or "default").strip() or "default"
        window_name = str(window_name or "").strip()
        if not subclass or not window_name:
            return None

        self.session.query(V2MonitorMetric).filter(
            V2MonitorMetric.subclass == subclass,
            V2MonitorMetric.league == league,
            V2MonitorMetric.regime == regime,
            V2MonitorMetric.window_name == window_name,
        ).delete(synchronize_session=False)

        row = V2MonitorMetric(
            subclass=subclass,
            league=league,
            regime=regime,
            window_name=window_name,
            n=int(n or 0),
            clv_rate=clv_rate,
            clv_magnitude=clv_magnitude,
            dispersion=dispersion,
            ewma_clv=ewma_clv,
            status=str(status or "gray"),
            updated_at=datetime.now(),
        )
        self.session.add(row)
        self.session.commit()
        return row.id

    def create_v2_backtest_run(
        self,
        *,
        run_tag: str,
        since: Optional[str],
        until: Optional[str],
        limit: Optional[int],
        min_books: int,
        total_fixtures: int,
        evaluated: int,
        skipped: int,
        fixtures_with_ah: int,
    ) -> int:
        row = V2BacktestRun(
            run_tag=str(run_tag or "historical"),
            since=str(since) if since else None,
            until=str(until) if until else None,
            limit=int(limit) if limit is not None else None,
            min_books=int(min_books),
            total_fixtures=int(total_fixtures),
            evaluated=int(evaluated),
            skipped=int(skipped),
            fixtures_with_ah=int(fixtures_with_ah),
            created_at=datetime.now(),
        )
        self.session.add(row)
        self.session.commit()
        return int(row.id)

    def bulk_insert_v2_backtest_rows(self, run_id: int, rows: List[Dict[str, Any]]):
        if not rows:
            return 0
        objs = []
        for r in rows:
            kickoff = _parse_match_time_value(r.get("kickoff"))
            objs.append(
                V2BacktestRow(
                    run_id=int(run_id),
                    fixture_id=str(r.get("fixture_id") or ""),
                    league=str(r.get("league") or ""),
                    kickoff=kickoff,
                    prototype=str(r.get("prototype") or ""),
                    subclass=str(r.get("subclass") or ""),
                    action_type=str(r.get("action_type") or ""),
                    strength=str(r.get("strength") or ""),
                    prediction_bias=str(r.get("prediction_bias") or "") or None,
                    signal_bucket=str(r.get("signal_bucket") or ""),
                    clv_prob=r.get("clv_prob"),
                    clv_logit=r.get("clv_logit"),
                    dispersion=r.get("dispersion"),
                    euro_favored_prob_delta=r.get("euro_favored_prob_delta"),
                    draw_prob_delta=r.get("draw_prob_delta"),
                    favored_side=str(r.get("favored_side") or ""),
                    actual_result=str(r.get("actual_result") or "") or None,
                    favored_win=r.get("favored_win"),
                    why=str(r.get("why") or "") or None,
                    created_at=datetime.now(),
                )
            )
        self.session.bulk_save_objects(objs)
        self.session.commit()
        return len(objs)

    def upsert_v2_daily_fixtures(
        self,
        *,
        window_tag: str,
        window_start: datetime,
        window_end: datetime,
        fixtures: List[Dict[str, Any]],
        source: str = "jingcai",
    ) -> int:
        window_tag = str(window_tag or "").strip()
        if not window_tag or not fixtures:
            return 0

        saved = 0
        for f in fixtures:
            fixture_id = str(f.get("fixture_id") or "").strip()
            if not fixture_id:
                continue
            kickoff = _parse_match_time_value(f.get("kickoff_time") or f.get("match_time"))
            existing = (
                self.session.query(V2DailyFixture)
                .filter(
                    V2DailyFixture.window_tag == window_tag,
                    V2DailyFixture.fixture_id == fixture_id,
                )
                .first()
            )
            if existing is None:
                row = V2DailyFixture(
                    window_tag=window_tag,
                    window_start=window_start,
                    window_end=window_end,
                    fixture_id=fixture_id,
                    match_num=str(f.get("match_num") or ""),
                    league=str(f.get("league") or ""),
                    home_team=str(f.get("home_team") or ""),
                    away_team=str(f.get("away_team") or ""),
                    kickoff_time=kickoff,
                    source=str(source or "jingcai"),
                    created_at=datetime.now(),
                )
                self.session.add(row)
            else:
                existing.window_start = window_start
                existing.window_end = window_end
                existing.match_num = str(f.get("match_num") or existing.match_num or "")
                existing.league = str(f.get("league") or existing.league or "")
                existing.home_team = str(f.get("home_team") or existing.home_team or "")
                existing.away_team = str(f.get("away_team") or existing.away_team or "")
                existing.kickoff_time = kickoff or existing.kickoff_time
            saved += 1

        self.session.commit()
        return saved

    def fetch_v2_daily_fixtures(self, window_tag: str) -> List[Dict[str, Any]]:
        window_tag = str(window_tag or "").strip()
        if not window_tag:
            return []
        rows = (
            self.session.query(V2DailyFixture)
            .filter(V2DailyFixture.window_tag == window_tag)
            .order_by(V2DailyFixture.kickoff_time.asc())
            .all()
        )
        out = []
        for r in rows:
            out.append(
                {
                    "window_tag": r.window_tag,
                    "window_start": r.window_start,
                    "window_end": r.window_end,
                    "fixture_id": r.fixture_id,
                    "match_num": r.match_num,
                    "league": r.league,
                    "home_team": r.home_team,
                    "away_team": r.away_team,
                    "kickoff_time": r.kickoff_time,
                    "source": r.source,
                    "created_at": r.created_at,
                }
            )
        return out

    def fetch_latest_predictions_for_fixtures(
        self, fixture_ids: List[str], *, prediction_period: str = "final"
    ) -> Dict[str, Dict[str, Any]]:
        if not fixture_ids:
            return {}

        period = str(prediction_period or "final").strip() or "final"
        rows = (
            self.session.query(MatchPrediction)
            .filter(
                MatchPrediction.fixture_id.in_([str(x) for x in fixture_ids]),
                MatchPrediction.prediction_period == period,
            )
            .order_by(MatchPrediction.updated_at.desc(), MatchPrediction.created_at.desc())
            .all()
        )
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            fid = str(r.fixture_id or "").strip()
            if not fid or fid in out:
                continue
            out[fid] = {
                "fixture_id": fid,
                "prediction_period": r.prediction_period,
                "prediction_text": r.prediction_text,
                "predicted_result": r.predicted_result,
                "confidence": r.confidence,
                "actual_result": r.actual_result,
                "actual_score": r.actual_score,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
        return out

    def fetch_latest_v2_script_output_for_fixtures(
        self, fixture_ids: List[str], *, prediction_period: str = "final"
    ) -> Dict[str, Dict[str, Any]]:
        if not fixture_ids:
            return {}
        period = str(prediction_period or "final").strip() or "final"
        rows = (
            self.session.query(V2ScriptOutput)
            .filter(
                V2ScriptOutput.fixture_id.in_([str(x) for x in fixture_ids]),
                V2ScriptOutput.prediction_period == period,
            )
            .order_by(V2ScriptOutput.created_at.desc())
            .all()
        )
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            fid = str(r.fixture_id or "").strip()
            if not fid or fid in out:
                continue
            out[fid] = {
                "fixture_id": fid,
                "prediction_period": r.prediction_period,
                "league": r.league,
                "mode": r.mode,
                "engine_version": r.engine_version,
                "prototype": r.prototype,
                "subclass": r.subclass,
                "action_type": r.action_type,
                "strength": r.strength,
                "prediction_bias": getattr(r, "prediction_bias", ""),
                "direction_hint": r.direction_hint,
                "why": r.why,
                "veto_tags": r.veto_tags or [],
                "signal_bucket": r.signal_bucket,
                "clv_prob": r.clv_prob,
                "clv_logit": r.clv_logit,
                "dispersion": r.dispersion,
                "nspf_top1": getattr(r, "nspf_top1", ""),
                "nspf_cover": getattr(r, "nspf_cover", ""),
                "nspf_confidence": getattr(r, "nspf_confidence", None),
                "nspf_scores": getattr(r, "nspf_scores", None),
                "decision_reason": getattr(r, "decision_reason", ""),
                "feedback_tag": getattr(r, "feedback_tag", ""),
                "upset_alert_level": getattr(r, "upset_alert_level", ""),
                "upset_alert_score": getattr(r, "upset_alert_score", None),
                "upset_direction": getattr(r, "upset_direction", ""),
                "upset_reasons": getattr(r, "upset_reasons", None) or [],
                "upset_guard_pick": getattr(r, "upset_guard_pick", ""),
                "created_at": r.created_at,
            }
        return out

    def save_v2_daily_report(
        self,
        *,
        target_date: str,
        report_path: Optional[str],
        window_start,
        window_end,
        total_matches: int,
        prog_cover_acc: Optional[float],
        prog_top1_acc: Optional[float],
        final_cover_acc: Optional[float],
        final_top1_acc: Optional[float],
        baseline_acc: Optional[float],
        metrics_json: Optional[Dict[str, Any]],
        markdown_content: str,
        rows: List[Dict[str, Any]],
    ) -> bool:
        try:
            record = self.session.query(V2DailyReport).filter_by(target_date=str(target_date)).first()
            if not record:
                record = V2DailyReport(
                    target_date=str(target_date),
                    window_start=window_start,
                    window_end=window_end,
                    report_path=str(report_path or ""),
                    total_matches=int(total_matches or 0),
                    prog_cover_acc=prog_cover_acc,
                    prog_top1_acc=prog_top1_acc,
                    final_cover_acc=final_cover_acc,
                    final_top1_acc=final_top1_acc,
                    baseline_acc=baseline_acc,
                    metrics_json=_json_safe(metrics_json or {}),
                    markdown_content=str(markdown_content or ""),
                )
                self.session.add(record)
            else:
                record.window_start = window_start
                record.window_end = window_end
                record.report_path = str(report_path or "")
                record.total_matches = int(total_matches or 0)
                record.prog_cover_acc = prog_cover_acc
                record.prog_top1_acc = prog_top1_acc
                record.final_cover_acc = final_cover_acc
                record.final_top1_acc = final_top1_acc
                record.baseline_acc = baseline_acc
                record.metrics_json = _json_safe(metrics_json or {})
                record.markdown_content = str(markdown_content or "")

            self.session.query(V2DailyReportRow).filter_by(target_date=str(target_date)).delete(synchronize_session=False)
            for item in rows or []:
                kickoff = _parse_match_time_value(item.get("kickoff"))
                self.session.add(
                    V2DailyReportRow(
                        target_date=str(target_date),
                        fixture_id=str(item.get("fixture_id") or ""),
                        match_num=str(item.get("match_num") or ""),
                        league=str(item.get("league") or ""),
                        home_team=str(item.get("home") or ""),
                        away_team=str(item.get("away") or ""),
                        kickoff=kickoff,
                        actual_result=str(item.get("actual") or ""),
                        prog_cover=str(item.get("prog_cover") or ""),
                        prog_top1=str(item.get("prog_top1") or ""),
                        final_cover=str(item.get("final_cover") or ""),
                        final_top1=str(item.get("final_top1") or ""),
                        baseline=str(item.get("baseline") or ""),
                        prog_cover_hit=bool(item.get("prog_cover_hit")) if item.get("prog_cover_hit") is not None else None,
                        prog_top1_hit=bool(item.get("prog_top1_hit")) if item.get("prog_top1_hit") is not None else None,
                        final_cover_hit=bool(item.get("final_cover_hit")) if item.get("final_cover_hit") is not None else None,
                        final_top1_hit=bool(item.get("final_top1_hit")) if item.get("final_top1_hit") is not None else None,
                        baseline_hit=bool(item.get("baseline_hit")) if item.get("baseline_hit") is not None else None,
                        subclass=str(item.get("subclass") or ""),
                        prototype=str(item.get("prototype") or ""),
                        prediction_bias=str(item.get("prediction_bias") or ""),
                        feedback_tag=str(item.get("feedback_tag") or ""),
                        prog_confidence=item.get("prog_confidence"),
                        league_subclass=str(item.get("league_subclass") or ""),
                    )
                )

            self.session.commit()
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.session.rollback()
            return False

    def get_v2_daily_report(self, target_date: str) -> Optional[Dict[str, Any]]:
        row = self.session.query(V2DailyReport).filter_by(target_date=str(target_date)).first()
        if not row:
            return None
        return {
            "target_date": row.target_date,
            "window_start": row.window_start,
            "window_end": row.window_end,
            "report_path": row.report_path,
            "total_matches": row.total_matches,
            "prog_cover_acc": row.prog_cover_acc,
            "prog_top1_acc": row.prog_top1_acc,
            "final_cover_acc": row.final_cover_acc,
            "final_top1_acc": row.final_top1_acc,
            "baseline_acc": row.baseline_acc,
            "metrics_json": row.metrics_json or {},
            "markdown_content": row.markdown_content or "",
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def get_v2_daily_report_rows(self, target_date: str) -> List[Dict[str, Any]]:
        rows = (
            self.session.query(V2DailyReportRow)
            .filter_by(target_date=str(target_date))
            .order_by(V2DailyReportRow.kickoff.asc(), V2DailyReportRow.match_num.asc())
            .all()
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "fixture_id": row.fixture_id,
                    "match_num": row.match_num,
                    "league": row.league,
                    "home": row.home_team,
                    "away": row.away_team,
                    "kickoff": row.kickoff,
                    "actual": row.actual_result,
                    "prog_cover": row.prog_cover,
                    "prog_top1": row.prog_top1,
                    "final_cover": row.final_cover,
                    "final_top1": row.final_top1,
                    "baseline": row.baseline,
                    "prog_cover_hit": row.prog_cover_hit,
                    "prog_top1_hit": row.prog_top1_hit,
                    "final_cover_hit": row.final_cover_hit,
                    "final_top1_hit": row.final_top1_hit,
                    "baseline_hit": row.baseline_hit,
                    "subclass": row.subclass,
                    "prototype": row.prototype,
                    "prediction_bias": row.prediction_bias,
                    "feedback_tag": row.feedback_tag,
                    "prog_confidence": row.prog_confidence,
                    "league_subclass": row.league_subclass,
                }
            )
        return out

    def list_v2_daily_report_dates(self, limit: int = 90) -> List[str]:
        rows = (
            self.session.query(V2DailyReport.target_date)
            .order_by(V2DailyReport.target_date.desc())
            .limit(int(limit or 90))
            .all()
        )
        return [str(r[0]) for r in rows if r and r[0]]

    def fetch_v2_snapshot_stats_for_fixtures(self, fixture_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        from sqlalchemy import text

        if not fixture_ids:
            return {}
        ids = [str(x) for x in fixture_ids]
        placeholders = ",".join([":id" + str(i) for i in range(len(ids))])
        params = {"id" + str(i): ids[i] for i in range(len(ids))}

        euro_sql = text(
            f"""
            SELECT fixture_id,
                   COUNT(1) AS cnt,
                   MAX(snapshot_time) AS last_time
            FROM v2_odds_snapshot
            WHERE fixture_id IN ({placeholders})
            GROUP BY fixture_id
            """
        )
        ah_sql = text(
            f"""
            SELECT fixture_id,
                   COUNT(1) AS cnt,
                   MAX(snapshot_time) AS last_time
            FROM v2_ah_snapshot
            WHERE fixture_id IN ({placeholders})
            GROUP BY fixture_id
            """
        )

        out: Dict[str, Dict[str, Any]] = {str(fid): {"euro_cnt": 0, "euro_last": None, "ah_cnt": 0, "ah_last": None} for fid in ids}
        try:
            euro_rows = self.session.execute(euro_sql, params).fetchall()
            for r in euro_rows:
                fid = str(r[0])
                if fid in out:
                    out[fid]["euro_cnt"] = int(r[1] or 0)
                    out[fid]["euro_last"] = r[2]
        except Exception:
            pass

        try:
            ah_rows = self.session.execute(ah_sql, params).fetchall()
            for r in ah_rows:
                fid = str(r[0])
                if fid in out:
                    out[fid]["ah_cnt"] = int(r[1] or 0)
                    out[fid]["ah_last"] = r[2]
        except Exception:
            pass
        return out

    def fetch_v2_monitor_metric(self, *, subclass: str, league: str, regime: str, window_name: str):
        subclass = str(subclass or "").strip()
        league = str(league or "").strip()
        regime = str(regime or "default").strip() or "default"
        window_name = str(window_name or "").strip()
        if not subclass or not window_name:
            return None
        return (
            self.session.query(V2MonitorMetric)
            .filter(
                V2MonitorMetric.subclass == subclass,
                V2MonitorMetric.league == league,
                V2MonitorMetric.regime == regime,
                V2MonitorMetric.window_name == window_name,
            )
            .order_by(V2MonitorMetric.updated_at.desc())
            .first()
        )

    def save_v2_odds_snapshot(
        self,
        *,
        fixture_id: str,
        book_id: str,
        snapshot_time: datetime,
        odds_h: str,
        odds_d: str,
        odds_a: str,
        quality_flag: int = 0,
    ):
        fixture_id = str(fixture_id or "").strip()
        book_id = str(book_id or "").strip()
        if not fixture_id or not book_id:
            return None

        row = V2OddsSnapshot(
            fixture_id=fixture_id,
            book_id=book_id,
            snapshot_time=snapshot_time,
            odds_h=str(odds_h or ""),
            odds_d=str(odds_d or ""),
            odds_a=str(odds_a or ""),
            quality_flag=int(quality_flag or 0),
            created_at=datetime.now(),
        )
        self.session.add(row)
        self.session.commit()
        return row.id

    def save_v2_ah_snapshot(
        self,
        *,
        fixture_id: str,
        book_id: str,
        snapshot_time: datetime,
        ah_line: str,
        price_home: str,
        price_away: str,
        is_mainline: bool = False,
        quality_flag: int = 0,
    ):
        fixture_id = str(fixture_id or "").strip()
        book_id = str(book_id or "").strip()
        if not fixture_id or not book_id:
            return None

        row = V2AHSnapshot(
            fixture_id=fixture_id,
            book_id=book_id,
            snapshot_time=snapshot_time,
            ah_line=str(ah_line or ""),
            price_home=str(price_home or ""),
            price_away=str(price_away or ""),
            is_mainline=bool(is_mainline),
            quality_flag=int(quality_flag or 0),
            created_at=datetime.now(),
        )
        self.session.add(row)
        self.session.commit()
        return row.id

    def fetch_v2_snapshot_bucket_counts(self, fixture_id: str):
        from sqlalchemy import text

        fixture_id = str(fixture_id or "").strip()
        if not fixture_id:
            return {"bucket_count": 0}

        q = text(
            """
            SELECT COUNT(DISTINCT DATE(snapshot_time) || ' ' || STRFTIME('%H', snapshot_time)) as bucket_count
            FROM v2_odds_snapshot
            WHERE fixture_id = :fixture_id
            """
        )
        try:
            row = self.session.execute(q, {"fixture_id": fixture_id}).fetchone()
            bucket_count = int(row[0] or 0) if row else 0
        except Exception:
            bucket_count = 0
        return {"bucket_count": bucket_count}

    def fetch_v2_odds_snapshots(self, fixture_id: str):
        fixture_id = str(fixture_id or "").strip()
        if not fixture_id:
            return []
        rows = (
            self.session.query(V2OddsSnapshot)
            .filter(V2OddsSnapshot.fixture_id == fixture_id)
            .order_by(V2OddsSnapshot.snapshot_time.asc())
            .all()
        )
        out = []
        for r in rows:
            out.append(
                {
                    "fixture_id": r.fixture_id,
                    "book_id": r.book_id,
                    "snapshot_time": r.snapshot_time,
                    "odds_h": r.odds_h,
                    "odds_d": r.odds_d,
                    "odds_a": r.odds_a,
                    "quality_flag": r.quality_flag,
                }
            )
        return out

    def fetch_v2_ah_snapshots(self, fixture_id: str):
        fixture_id = str(fixture_id or "").strip()
        if not fixture_id:
            return []
        rows = (
            self.session.query(V2AHSnapshot)
            .filter(V2AHSnapshot.fixture_id == fixture_id)
            .order_by(V2AHSnapshot.snapshot_time.asc())
            .all()
        )
        out = []
        for r in rows:
            out.append(
                {
                    "fixture_id": r.fixture_id,
                    "book_id": r.book_id,
                    "snapshot_time": r.snapshot_time,
                    "ah_line": r.ah_line,
                    "price_home": r.price_home,
                    "price_away": r.price_away,
                    "is_mainline": bool(r.is_mainline),
                    "quality_flag": r.quality_flag,
                }
            )
        return out

    def _ensure_match_predictions_columns(self):
        """为已有 SQLite 库补齐运行期需要的列。"""
        try:
            with self.engine.begin() as conn:
                columns = {
                    row[1]
                    for row in conn.exec_driver_sql("PRAGMA table_info(match_predictions)").fetchall()
                }
                if "predicted_result" not in columns:
                    conn.exec_driver_sql(
                        "ALTER TABLE match_predictions ADD COLUMN predicted_result VARCHAR(100)"
                    )
        except Exception as e:
            logger.warning(f"match_predictions 列检查失败: {e}")

    @staticmethod
    def extract_prediction_recommendation(prediction_text):
        """从预测报告中提取不让球“竞彩推荐”原文。"""
        if not prediction_text:
            return None

        if not isinstance(prediction_text, (str, bytes)):
            try:
                import json as _json

                prediction_text = _json.dumps(prediction_text, ensure_ascii=False)
            except Exception:
                prediction_text = str(prediction_text)

        patterns = [
            r'[\-\*\s]*竞彩推荐(?:（不让球）|\(不让球\))?[\*\s]*[：:]\s*([^\n\r]+)',
            r'[\-\*\s]*不让球推荐[\*\s]*[：:]\s*([^\n\r]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, prediction_text)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'^[\-\*\s]+', '', value)
                value = re.sub(r'[\*]+', '', value)
                value = value.replace("\\n", "\n").replace("\\r", "\r")
                value = re.split(r'[\n\r]', value, maxsplit=1)[0].strip()
                value = re.split(r'\s*(?:（不让球[^）]*）|\(不让球[^)]*\)|——|--)\s*', value, maxsplit=1)[0].strip()
                value = re.split(r'(?:竞彩让球推荐|让球推荐|竞彩置信度|比分参考|进球数参考)', value, maxsplit=1)[0].strip()
                value = re.sub(r'\s*（不让球.*?\)|\s*\(不让球.*?\)', '', value)
                return value[:100]

        return None

    def save_prediction(self, match_data, period='pre_24h'):
        """保存或更新预测结果，支持时间段标识"""
        try:
            fixture_id = match_data.get("fixture_id")
            if not fixture_id:
                return False
                
            # 尝试查找是否存在相同fixture_id和period的记录
            record = self.session.query(MatchPrediction).filter_by(
                fixture_id=fixture_id, 
                prediction_period=period
            ).first()
            
            match_time = _parse_match_time_value(match_data.get("match_time"))

            prediction_text = match_data.get("llm_prediction", "")
            if prediction_text is None:
                prediction_text = ""
            if not isinstance(prediction_text, (str, bytes)):
                try:
                    import json as _json

                    prediction_text = _json.dumps(prediction_text, ensure_ascii=False)
                except Exception:
                    prediction_text = str(prediction_text)
            predicted_result = self.extract_prediction_recommendation(prediction_text)

            safe_raw_data = _json_safe(match_data)

            if not record:
                # 新建记录
                record = MatchPrediction(
                    fixture_id=fixture_id,
                    match_num=match_data.get("match_num"),
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    prediction_period=period,
                    raw_data=safe_raw_data,
                    prediction_text=prediction_text,
                    predicted_result=predicted_result,
                    htft_prediction_text=match_data.get("htft_prediction", "")
                )
                self.session.add(record)
            else:
                # 更新记录
                record.raw_data = safe_raw_data
                if prediction_text:
                    record.prediction_text = prediction_text
                    record.predicted_result = predicted_result
                if match_data.get("htft_prediction"):
                    record.htft_prediction_text = match_data.get("htft_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"数据库保存失败: {e}")
            return False
            
    def close(self):
        self.session.close()

    def get_user(self, username):
        return self.session.query(User).filter_by(username=username).first()

    def get_prediction(self, match_num):
        """根据比赛编号获取最新的全场预测记录"""
        return self.session.query(MatchPrediction).filter(
            MatchPrediction.match_num.like(f"%{match_num}%")
        ).order_by(MatchPrediction.created_at.desc()).first()

    def get_prediction_by_period(self, fixture_id, period):
        """根据时间段获取预测结果"""
        return self.session.query(MatchPrediction).filter_by(
            fixture_id=fixture_id, 
            prediction_period=period
        ).first()
    
    def get_all_predictions_by_fixture(self, fixture_id):
        """获取某场比赛的所有时间段预测结果"""
        return self.session.query(MatchPrediction).filter_by(
            fixture_id=fixture_id
        ).order_by(MatchPrediction.created_at.desc()).all()

    def save_bball_prediction(self, match_data):
        """保存篮球预测结果"""
        try:
            fixture_id = match_data.get("fixture_id")
            if not fixture_id:
                return False
                
            record = self.session.query(BasketballPrediction).filter_by(
                fixture_id=fixture_id
            ).first()
            
            match_time = _parse_match_time_value(match_data.get("match_time"))

            if not record:
                record = BasketballPrediction(
                    fixture_id=fixture_id,
                    match_num=match_data.get("match_num"),
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    raw_data=match_data,
                    prediction_text=match_data.get("llm_prediction", "")
                )
                self.session.add(record)
            else:
                record.raw_data = match_data
                if match_data.get("llm_prediction"):
                    record.prediction_text = match_data.get("llm_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"篮球数据库保存失败: {e}")
            return False

    def get_bball_prediction_by_fixture(self, fixture_id):
        """获取某场篮球比赛的预测结果"""
        return self.session.query(BasketballPrediction).filter_by(
            fixture_id=fixture_id
        ).first()

    def save_sfc_prediction(self, match_data):
        """保存胜负彩预测结果"""
        try:
            issue_num = match_data.get("issue_num")
            match_num = match_data.get("match_num")
            
            if not issue_num or not match_num:
                return False
                
            record = self.session.query(SfcPrediction).filter_by(
                issue_num=issue_num,
                match_num=match_num
            ).first()
            
            match_time = _parse_match_time_value(match_data.get("match_time"))

            if not record:
                record = SfcPrediction(
                    issue_num=issue_num,
                    fixture_id=match_data.get("fixture_id", ""),
                    match_num=match_num,
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    raw_data=match_data,
                    prediction_text=match_data.get("llm_prediction", "")
                )
                self.session.add(record)
            else:
                record.raw_data = match_data
                if match_data.get("llm_prediction"):
                    record.prediction_text = match_data.get("llm_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"胜负彩数据库保存失败: {e}")
            return False

    def get_sfc_prediction(self, issue_num, match_num):
        """获取某场胜负彩比赛的预测结果"""
        return self.session.query(SfcPrediction).filter_by(
            issue_num=issue_num,
            match_num=match_num
        ).first()

    def get_parlays_by_date(self, target_date):
        """获取指定日期的串关方案"""
        return self.session.query(DailyParlays).filter_by(target_date=target_date).first()

    def save_parlays(self, target_date, current_parlay, previous_parlay=None, comparison_text=None):
        """保存当天的串关方案"""
        try:
            record = self.get_parlays_by_date(target_date)
            if not record:
                record = DailyParlays(
                    target_date=target_date,
                    current_parlay=current_parlay,
                    previous_parlay=previous_parlay,
                    comparison_text=comparison_text
                )
                self.session.add(record)
            else:
                record.current_parlay = current_parlay
                if previous_parlay is not None:
                    record.previous_parlay = previous_parlay
                if comparison_text is not None:
                    record.comparison_text = comparison_text
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"保存串关方案失败: {e}")
            return False

    def get_predictions_by_date(self, target_date):
        """获取指定日期的所有预测（日周期窗口: 目标日 12:00 ~ 次日 12:00）"""
        from datetime import datetime, timedelta
        
        try:
            start_date = datetime.strptime(target_date, "%Y-%m-%d")
            window_start = start_date.replace(hour=12, minute=0, second=0)
            window_end = (start_date + timedelta(days=1)).replace(hour=12, minute=0, second=0)
            
            records = self.session.query(MatchPrediction).filter(
                MatchPrediction.match_time >= window_start,
                MatchPrediction.match_time < window_end
            ).all()
        except Exception as e:
            print(f"查询日期失败: {e}")
            records = []
            
        # 相同fixture_id可能有多个period，repredicted(历史重新预测)最高优先，其次final/pre_12h/pre_24h
        result_map = {}
        priority = {'repredicted': 5, 'final': 3, 'pre_12h': 2, 'pre_24h': 1}
        for r in records:
            fid = r.fixture_id
            if fid not in result_map:
                result_map[fid] = r
            else:
                if priority.get(r.prediction_period, 0) > priority.get(result_map[fid].prediction_period, 0):
                    result_map[fid] = r
        return list(result_map.values())

    def update_actual_result(self, fixture_id, score, bqc_result=None):
        """更新比赛实际赛果"""
        try:
            records = self.session.query(MatchPrediction).filter_by(fixture_id=fixture_id).all()
            actual_result = _parse_actual_result_from_score(score)
            for record in records:
                record.actual_score = score
                if actual_result:
                    record.actual_result = actual_result
                if bqc_result:
                    record.actual_bqc = bqc_result
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"更新赛果失败: {e}")
            return False

    def get_daily_review(self, target_date):
        """获取某日的复盘记录"""
        return self.session.query(DailyReview).filter_by(target_date=target_date).first()

    def save_euro_odds(self, match_info, company_odds):
        """批量保存欧赔历史数据
        match_info: dict with fixture_id, match_num, league, home_team, away_team, match_time, actual_score, actual_result
        company_odds: list of dict, each with company, init_home, init_draw, init_away, live_home, live_draw, live_away
        """
        try:
            fixture_id = match_info.get("fixture_id")
            if not fixture_id:
                return False
            saved = 0
            for co in company_odds:
                if not co.get("init_home") or not co.get("live_home"):
                    continue
                record = EuroOddsHistory(
                    fixture_id=fixture_id,
                    match_num=match_info.get("match_num", ""),
                    league=match_info.get("league", ""),
                    home_team=match_info.get("home_team", ""),
                    away_team=match_info.get("away_team", ""),
                    match_time=match_info.get("match_time_parsed"),
                    company=co.get("company", ""),
                    init_home=co.get("init_home"),
                    init_draw=co.get("init_draw"),
                    init_away=co.get("init_away"),
                    live_home=co.get("live_home"),
                    live_draw=co.get("live_draw"),
                    live_away=co.get("live_away"),
                    actual_score=match_info.get("actual_score", ""),
                    actual_result=match_info.get("actual_result", ""),
                )
                self.session.add(record)
                saved += 1
            self.session.commit()
            return saved
        except Exception as e:
            self.session.rollback()
            logger.error(f"保存欧赔历史失败: {e}")
            return 0

    def save_daily_review(self, target_date, review_content, htft_review_content=None):
        """保存某日的复盘记录"""
        try:
            record = self.get_daily_review(target_date)
            if not record:
                record = DailyReview(
                    target_date=target_date,
                    review_content=review_content,
                    htft_review_content=htft_review_content
                )
                self.session.add(record)
            else:
                if review_content is not None:
                    record.review_content = review_content
                if htft_review_content is not None:
                    record.htft_review_content = htft_review_content
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"保存复盘失败: {e}")
            return False

if __name__ == "__main__":
    db = Database()
    print("数据库初始化成功！")
