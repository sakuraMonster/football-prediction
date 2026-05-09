# -*- coding: utf-8 -*-
import os
import sys
import json
sys.path.append(os.getcwd())

from src.crawler.leisu_crawler import LeisuCrawler
from src.processor.data_fusion import inject_leisu_data

with open('data/today_matches.json', 'r', encoding='utf-8') as f:
    matches = json.load(f)

match = next(m for m in matches if m.get('match_num') == '周三007')
print('MATCH=', match.get('match_num'), match.get('home_team'), 'vs', match.get('away_team'))
leisu = LeisuCrawler(headless=True)
try:
    ok = inject_leisu_data(match, leisu)
    print('INJECT_OK=', ok)
    print('LEISU_KEYS=', [k for k in match.keys() if 'leisu' in k or 'inj' in k or 'goal' in k or 'standing' in k])
    print('INJURIES_TEXT=', ((match.get('injuries_detailed') or {}).get('injuries_text', ''))[:500])
    print('GOAL_DIST=', match.get('goal_distribution'))
    print('STANDINGS=', match.get('standings_info'))
    print('H2H_LEISU=', match.get('h2h_leisu'))
    print('RECENT_LEISU=', match.get('recent_leisu'))
finally:
    leisu.close()
