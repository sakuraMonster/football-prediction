import json
from src.crawler.leisu_crawler import LeisuCrawler

def main():
    leisu = LeisuCrawler(headless=True)
    print("Init done.")
    try:
        # Pick a match that exists
        data = leisu.fetch_match_data("布拉加", "弗赖堡")
        print("Data fetched:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        leisu.close()

if __name__ == '__main__':
    main()
