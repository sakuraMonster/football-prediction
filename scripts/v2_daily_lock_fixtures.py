import os
import sys
from datetime import datetime
from typing import Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from loguru import logger

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.db.database import Database
from src.market_script_v2.daily_window import compute_today_window


def lock_today_window(now: Optional[datetime] = None):
    now = now or datetime.now()
    window_start, window_end, window_tag = compute_today_window(now)

    crawler = JingcaiCrawler()
    matches = crawler.fetch_matches_in_window(window_start, window_end)
    if not matches:
        logger.warning(f"窗口内未抓到比赛 window_tag={window_tag}")
        return 0, window_tag

    fixtures = []
    for m in matches:
        fixtures.append(
            {
                "fixture_id": m.get("fixture_id"),
                "match_num": m.get("match_num"),
                "league": m.get("league"),
                "home_team": m.get("home_team"),
                "away_team": m.get("away_team"),
                "kickoff_time": m.get("match_time"),
            }
        )

    db = Database()
    saved = db.upsert_v2_daily_fixtures(
        window_tag=window_tag,
        window_start=window_start,
        window_end=window_end,
        fixtures=fixtures,
        source="jingcai",
    )
    db.close()

    logger.info(
        f"✅ 今日窗口赛程已锁定 window_tag={window_tag} start={window_start} end={window_end} fixtures={saved}"
    )
    return saved, window_tag


if __name__ == "__main__":
    saved, window_tag = lock_today_window()
    print(f"✅ v2 今日赛程锁定完成 window_tag={window_tag} fixtures={saved}")
