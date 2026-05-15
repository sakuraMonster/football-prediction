import os
import sys
import time
from datetime import datetime
from typing import Dict, Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from loguru import logger

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.crawler.odds_crawler import OddsCrawler
from src.db.database import Database
from src.llm.predictor import LLMPredictor
from src.market_script_v2.daily_window import compute_today_window


def run_final_predictions(
    window_tag: str,
    *,
    sleep_s: float = 0.5,
    limit: Optional[int] = None,
    force_engine_mode: str = "v2_full",
):
    if not (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
        logger.warning("缺少 LLM_API_KEY（或 OPENAI_API_KEY），无法执行最终预测。先完成 config/.env 配置后再运行。")
        return 0

    db = Database()
    fixtures = db.fetch_v2_daily_fixtures(window_tag)
    if not fixtures:
        db.close()
        logger.warning(f"未找到已锁定赛程 window_tag={window_tag}")
        return 0

    if limit is not None:
        fixtures = fixtures[: int(limit)]

    window_start = fixtures[0].get("window_start")
    window_end = fixtures[0].get("window_end")

    jingcai = JingcaiCrawler()
    jc_by_fixture: Dict[str, dict] = {}
    if window_start and window_end:
        try:
            jc_matches = jingcai.fetch_matches_in_window(window_start, window_end)
            jc_by_fixture = {str(m.get("fixture_id")): m for m in jc_matches if m.get("fixture_id")}
        except Exception:
            jc_by_fixture = {}

    os.environ["PREDICTION_MARKET_ENGINE_MODE"] = str(force_engine_mode)
    predictor = LLMPredictor()
    odds_crawler = OddsCrawler()

    predicted = 0
    for i, f in enumerate(fixtures, start=1):
        fixture_id = str(f.get("fixture_id") or "").strip()
        if not fixture_id:
            continue

        try:
            time.sleep(float(sleep_s))
            details = odds_crawler.fetch_match_details(
                fixture_id,
                home_team=f.get("home_team"),
                away_team=f.get("away_team"),
            )
        except Exception as e:
            logger.warning(f"fixture_id={fixture_id} 抓取详情失败: {e}")
            continue

        base = {
            "fixture_id": fixture_id,
            "match_num": f.get("match_num"),
            "league": f.get("league"),
            "home_team": f.get("home_team"),
            "away_team": f.get("away_team"),
            "match_time": f.get("kickoff_time") or f.get("match_time"),
        }
        jc = jc_by_fixture.get(fixture_id) or {}
        if jc.get("odds"):
            base["odds"] = jc.get("odds")

        match_data = {}
        match_data.update(base)
        match_data.update(details or {})

        try:
            prediction_text = predictor.predict(
                match_data,
                period="final",
                total_matches_count=len(fixtures),
                is_sfc=False,
            )
            match_data["llm_prediction"] = prediction_text
            db.save_prediction(match_data, period="final")
            predicted += 1
            logger.info(f"[{i}/{len(fixtures)}] fixture_id={fixture_id} 最终预测已写入")
        except Exception as e:
            logger.warning(f"fixture_id={fixture_id} 预测失败: {e}")
            continue

    db.close()
    return predicted


if __name__ == "__main__":
    window_tag = None
    if len(sys.argv) > 1 and sys.argv[1] not in {"-", ""}:
        window_tag = sys.argv[1]

    if not window_tag:
        _, _, window_tag = compute_today_window(datetime.now())

    predicted = run_final_predictions(window_tag)
    print(f"✅ v2 最终预测完成 window_tag={window_tag} predicted={predicted}")
