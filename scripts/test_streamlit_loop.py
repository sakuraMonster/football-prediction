import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simulate Streamlit's loop
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def run_streamlit_sim():
    from src.crawler.leisu_crawler import LeisuCrawler
    leisu = LeisuCrawler(headless=True)
    match = {
        "match_num": "周三004",
        "home_team": "柏太阳神",
        "away_team": "浦和红钻",
        "match_time": "2026-05-06 18:00"
    }
    try:
        data = leisu.fetch_match_data(match['home_team'], match['away_team'])
        print(f"Data: {data is not None}")
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

loop.run_in_executor(None, run_streamlit_sim)

# run loop for a bit
loop.run_until_complete(asyncio.sleep(5))
