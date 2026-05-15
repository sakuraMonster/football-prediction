import os
import sys
import datetime
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from loguru import logger

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.crawler.odds_crawler import OddsCrawler
from src.db.database import Database


def _normalize_book_id(name: str) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return "unknown"
    if "澳门" in text or "*门" in text:
        return "macau"
    if "bet365" in text or "t3*5" in text:
        return "bet365"
    safe = []
    for ch in text:
        if ch.isalnum() or ch == "_":
            safe.append(ch)
        elif ch.isspace() or ch in {"-", ".", "/"}:
            safe.append("_")
    out = "".join(safe)
    out = "_".join([p for p in out.split("_") if p])
    return out[:50] or "unknown"


def _parse_ah_live_triplet(live_text: str):
    parts = [p.strip() for p in str(live_text or "").split("|")]
    if len(parts) < 3:
        return "", "", ""
    up = parts[0].strip().replace("↑", "").replace("↓", "")
    line = parts[1].strip()
    down = parts[2].strip().replace("↑", "").replace("↓", "")
    return line, up, down


def collect_for_date(target_date=None, sleep_s=0.4, limit=None):
    jingcai = JingcaiCrawler()
    odds_crawler = OddsCrawler()
    db = Database()

    matches = jingcai.fetch_today_matches(target_date=target_date)
    if not matches:
        logger.warning("未抓到比赛列表")
        db.close()
        return 0

    if limit:
        matches = matches[: int(limit)]

    saved = 0
    snapshot_time = datetime.datetime.now()

    for i, m in enumerate(matches, start=1):
        fixture_id = m.get("fixture_id")
        if not fixture_id:
            continue

        try:
            time.sleep(float(sleep_s))
            details = odds_crawler.fetch_match_details(
                fixture_id,
                home_team=m.get("home_team"),
                away_team=m.get("away_team"),
            )
        except Exception as e:
            logger.warning(f"fixture_id={fixture_id} 抓取失败: {e}")
            continue

        europe_odds = details.get("europe_odds") or []
        for row in europe_odds:
            book_id = _normalize_book_id(row.get("company"))
            odds_h = row.get("live_home") or row.get("init_home") or ""
            odds_d = row.get("live_draw") or row.get("init_draw") or ""
            odds_a = row.get("live_away") or row.get("init_away") or ""
            try:
                db.save_v2_odds_snapshot(
                    fixture_id=str(fixture_id),
                    book_id=book_id,
                    snapshot_time=snapshot_time,
                    odds_h=str(odds_h),
                    odds_d=str(odds_d),
                    odds_a=str(odds_a),
                    quality_flag=0,
                )
                saved += 1
            except Exception as e:
                logger.warning(f"fixture_id={fixture_id} 欧赔落库失败: {e}")

        asian = details.get("asian_odds") or {}
        for book_id in ["macau", "bet365"]:
            live = ((asian.get(book_id) or {}).get("live")) or ""
            if not live:
                continue
            line, up, down = _parse_ah_live_triplet(live)
            try:
                db.save_v2_ah_snapshot(
                    fixture_id=str(fixture_id),
                    book_id=book_id,
                    snapshot_time=snapshot_time,
                    ah_line=line,
                    price_home=up,
                    price_away=down,
                    is_mainline=(book_id == "macau"),
                    quality_flag=0,
                )
                saved += 1
            except Exception as e:
                logger.warning(f"fixture_id={fixture_id} 亚盘落库失败: {e}")

        logger.info(f"[{i}/{len(matches)}] fixture_id={fixture_id} 快照已写入")

    db.close()
    return saved


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    limit_arg = sys.argv[2] if len(sys.argv) > 2 else None
    saved = collect_for_date(date_arg, limit=limit_arg)
    print(f"✅ v2 快照写入完成，新增 {saved} 条")

