import sys
import os
import json
import traceback
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crawler.leisu_crawler import LeisuCrawler

def main():
    print("Initializing crawler...")
    leisu = LeisuCrawler(headless=True)
    try:
        print("Fetching data for 柏太阳神 vs 浦和红钻...")
        data = leisu.fetch_match_data("柏太阳神", "浦和红钻")
        if data:
            print("Data fetched successfully!")
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("Failed to fetch data (returned None).")
    except Exception as e:
        print("Exception occurred:")
        traceback.print_exc()
    finally:
        leisu.close()

if __name__ == '__main__':
    main()
