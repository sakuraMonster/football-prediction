"""
从500.com批量拉取最近N天比赛数据（含欧赔初赔/临赔+赛果），存入 euro_odds_history 表。
使用方法: python scripts/crawl_euro_odds_history.py [天数，默认30]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from loguru import logger
import time

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.crawler.euro_odds_crawler import EuroOddsCrawler
from src.db.database import Database


def safe_float(s, default=None):
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_result(score_str):
    """从比分字符串(如 '2:1')解析胜平负结果"""
    if not score_str or ':' not in score_str:
        return None
    parts = score_str.split(':')
    try:
        home = int(parts[0].strip())
        away = int(parts[1].strip())
        if home > away:
            return "胜"
        elif home < away:
            return "负"
        else:
            return "平"
    except ValueError:
        return None


def crawl_date_range(days=30):
    """拉取最近N天的历史比赛+欧赔数据"""
    jingcai = JingcaiCrawler()
    euro_crawler = EuroOddsCrawler()
    db = Database()

    today = datetime.now()
    total_matches = 0
    total_odds = 0

    for i in range(days):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        logger.info(f"\n{'='*60}\n处理日期: {target_date}\n{'='*60}")

        # Step 1: 从500.com历史页面拉取当天已完赛的比赛列表
        matches = jingcai.fetch_history_matches(target_date)
        if not matches:
            logger.warning(f"日期 {target_date} 没有拉到比赛数据")
            continue

        logger.info(f"日期 {target_date} 共 {len(matches)} 场比赛")

        for match in matches:
            fixture_id = match.get("fixture_id")
            if not fixture_id:
                continue

            actual_score = match.get("actual_score", "")
            actual_result = parse_result(actual_score)

            match_time_str = match.get("match_time", "")
            match_time_parsed = None
            if match_time_str:
                try:
                    match_time_parsed = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
                except:
                    pass

            match_info = {
                "fixture_id": fixture_id,
                "match_num": match.get("match_num", ""),
                "league": match.get("league", ""),
                "home_team": match.get("home_team", ""),
                "away_team": match.get("away_team", ""),
                "match_time_parsed": match_time_parsed,
                "actual_score": actual_score,
                "actual_result": actual_result,
            }

            # Step 2: 从欧赔分析页拉取初赔/临赔（间隔0.5s防止限流）
            time.sleep(0.5)
            company_odds = euro_crawler.fetch_euro_odds(fixture_id)
            if not company_odds:
                logger.warning(f"  fixture_id={fixture_id} 无欧赔数据，跳过")
                continue

            # Step 3: 存入数据库
            saved = db.save_euro_odds(match_info, company_odds)
            total_matches += 1
            total_odds += saved
            logger.info(
                f"  ✅ [{match.get('match_num','')}] {match.get('home_team','')} vs {match.get('away_team','')} "
                f"赛果={actual_score}({actual_result}) 保存{saved}条欧赔"
            )

    db.close()
    logger.info(f"\n{'='*60}")
    logger.info(f"拉取完成! 共处理 {total_matches} 场比赛，保存 {total_odds} 条欧赔记录")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    logger.info(f"开始拉取最近 {days} 天的历史数据...")
    crawl_date_range(days)
