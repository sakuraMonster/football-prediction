import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crawler.leisu_crawler import LeisuCrawler
from src.processor.data_fusion import inject_leisu_data

def main():
    leisu = LeisuCrawler(headless=True)
    match = {
        "match_num": "周三004",
        "home_team": "柏太阳神",
        "away_team": "浦和红钻",
        "match_time": "2026-05-06 18:00"
    }
    print("Injecting...")
    res = inject_leisu_data(match, leisu)
    print(f"Result: {res}")
    leisu.close()

if __name__ == '__main__':
    main()
