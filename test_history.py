from src.crawler.jingcai_crawler import JingcaiCrawler
c = JingcaiCrawler()
matches = c.fetch_history_matches('2026-04-26')
print(f"Fetched {len(matches)} matches")
for m in matches[:5]:
    print(f"  {m['match_num']} [{m['league']}] {m['home_team']} vs {m['away_team']} | {m['actual_score']} | NSPF={m['odds']['nspf']}")
