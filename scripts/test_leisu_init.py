import traceback
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.crawler.leisu_crawler import LeisuCrawler
    print("Import successful")
    leisu = LeisuCrawler(headless=True)
    print("Init successful")
    leisu.close()
except Exception as e:
    print("Error occurred:")
    traceback.print_exc()
