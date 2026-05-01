import json
import sqlite3
conn = sqlite3.connect('data/football.db')
cursor = conn.cursor()
cursor.execute("SELECT raw_data FROM match_predictions WHERE match_num LIKE '%周二002%' ORDER BY created_at DESC LIMIT 1")
row = cursor.fetchone()
if row:
    raw = json.loads(row[0])
    if 'asian_odds' in raw:
        print('Asian Odds:', json.dumps(raw['asian_odds'], ensure_ascii=False, indent=2))
    else:
        print('No asian odds in raw data')