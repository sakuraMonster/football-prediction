import sqlite3
import json

conn = sqlite3.connect('data/football.db')
cur = conn.cursor()
cur.execute("SELECT match_num, home_team, away_team, raw_data FROM match_predictions WHERE home_team LIKE '%科隆%' AND away_team LIKE '%勒沃%' ORDER BY id DESC LIMIT 1")
res = cur.fetchone()
if res:
    print(f"Found: {res[0]} {res[1]} vs {res[2]}")
    with open('temp_kelong.json', 'w', encoding='utf-8') as f:
        json.dump(json.loads(res[3]), f, ensure_ascii=False, indent=2)
else:
    print("Not found")
conn.close()
