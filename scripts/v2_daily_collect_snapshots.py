import os
import sys
import time
from datetime import datetime
from typing import Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from loguru import logger

from src.crawler.odds_crawler import OddsCrawler
from src.db.database import Database
from src.market_script_v2.daily_window import compute_today_window


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


def collect_snapshots_for_window(window_tag: str, sleep_s: float = 0.4, limit: Optional[int] = None):
    db = Database()
    fixtures = db.fetch_v2_daily_fixtures(window_tag)
    if not fixtures:
        db.close()
        logger.warning(f"未找到已锁定赛程 window_tag={window_tag}")
        return 0

    now = datetime.now()
    remaining = []
    for f in fixtures:
        kickoff = f.get("kickoff_time")
        if kickoff is not None and kickoff < now:
            continue
        remaining.append(f)

    if limit is not None:
        remaining = remaining[: int(limit)]

    odds_crawler = OddsCrawler()
    saved = 0
    snapshot_time = datetime.now()

    for i, f in enumerate(remaining, start=1):
        fixture_id = f.get("fixture_id")
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

        logger.info(f"[{i}/{len(remaining)}] fixture_id={fixture_id} 快照已写入")

    db.close()
    return saved


if __name__ == "__main__":
    window_tag = None
    limit = None
    if len(sys.argv) > 1 and sys.argv[1] not in {"-", ""}:
        window_tag = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] not in {"-", ""}:
        limit = int(sys.argv[2])

    if not window_tag:
        _, _, window_tag = compute_today_window(datetime.now())

    saved = collect_snapshots_for_window(window_tag, limit=limit)
    print(f"✅ v2 快照写入完成 window_tag={window_tag} 新增 {saved} 条")
