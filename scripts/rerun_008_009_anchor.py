# -*- coding: utf-8 -*-
import os, sys, json
sys.path.append(os.getcwd())
from src.llm.predictor import LLMPredictor

with open('data/today_matches.json', 'r', encoding='utf-8') as f:
    matches = json.load(f)

predictor = LLMPredictor()
selected = [m for m in matches if m.get('match_num') in ('周三008', '周三009')]
other_matches = [m for m in matches if m.get('match_num') not in ('周三008', '周三009')]
results = []
for match in selected:
    anchor = predictor._build_market_anchor_summary(match)
    result, period = predictor.predict(match, total_matches_count=len(matches), other_matches_context=other_matches)
    results.append({
        'match_num': match.get('match_num'),
        'home_team': match.get('home_team'),
        'away_team': match.get('away_team'),
        'period': period,
        'market_anchor': anchor,
        'prediction': result,
    })
with open('data/tmp_008_009_anchor_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print('DONE')
