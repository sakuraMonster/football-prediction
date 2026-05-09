# -*- coding: utf-8 -*-
import os
import sys
import json
sys.path.append(os.getcwd())

from src.crawler.leisu_crawler import LeisuCrawler
from src.processor.data_fusion import inject_leisu_data
from src.llm.predictor import LLMPredictor

with open('data/today_matches.json', 'r', encoding='utf-8') as f:
    matches = json.load(f)

match = next(m for m in matches if m.get('match_num') == '周三007')
other_matches = [m for m in matches if m.get('match_num') != '周三007']
leisu = LeisuCrawler(headless=True)
try:
    inject_leisu_data(match, leisu)
finally:
    leisu.close()

predictor = LLMPredictor()
result, period = predictor.predict(match, total_matches_count=len(matches), other_matches_context=other_matches)

payload = {
    'period': period,
    'injuries_text': ((match.get('injuries_detailed') or {}).get('injuries_text', '')),
    'goal_distribution': match.get('goal_distribution'),
    'prediction': result,
}
with open('data/tmp_rerun_007_result.json', 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print('DONE')
