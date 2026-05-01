import json
import sqlite3

conn = sqlite3.connect('data/football.db')
cursor = conn.cursor()
cursor.execute("SELECT raw_data FROM match_predictions WHERE match_num LIKE '%周二001%' ORDER BY created_at DESC LIMIT 1")
row = cursor.fetchone()
if row:
    raw = json.loads(row[0])
    print('SPF (让球):', raw.get('odds', {}).get('spf', []))
    print('Rangqiu:', raw.get('odds', {}).get('rangqiu', ''))
