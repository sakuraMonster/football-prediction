# -*- coding: utf-8 -*-
import sys
import os
sys.path.append(os.getcwd())
from src.crawler.leisu_crawler import LeisuCrawler

crawler = LeisuCrawler(headless=True)
try:
    data = crawler.fetch_match_data('阿尔梅勒', '格拉夫', '2026-05-06 18:00')
    print('HAS_DATA=', bool(data))
    print('DATA=', data)
finally:
    crawler.close()
