import json
import sqlite3

conn = sqlite3.connect('data/football.db')
cursor = conn.cursor()

def get_match_info(match_num):
    cursor.execute(f"SELECT home_team, away_team, raw_data FROM match_predictions WHERE match_num LIKE '%{match_num}%' ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        raw = json.loads(row[2])
        return {
            'match': f"{row[0]} vs {row[1]}",
            'odds': raw.get('asian_odds', {}),
            'nspf': raw.get('odds', {}).get('nspf', [])
        }
    return None

m1 = get_match_info('周二001')
m2 = get_match_info('周二002')

print('--- 周二001 ---')
print(json.dumps(m1, ensure_ascii=False, indent=2))
print('\n--- 周二002 ---')
print(json.dumps(m2, ensure_ascii=False, indent=2))
