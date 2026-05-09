# -*- coding: utf-8 -*-
import sys
import os
sys.path.append(os.getcwd())
from src.crawler.leisu_crawler import LeisuCrawler
from src.processor.data_fusion import inject_leisu_data

leisu = LeisuCrawler(headless=True)
match = {
    'match_num': '周三005',
    'home_team': '阿尔梅勒',
    'away_team': '格拉夫',
    'match_time': '2026-05-06 18:00'
}
print('Injecting...')
try:
    print('Result=', inject_leisu_data(match, leisu))
    print('Match keys=', [k for k in match.keys() if 'leisu' in k or 'inj' in k or 'goal' in k])
finally:
    leisu.close()
