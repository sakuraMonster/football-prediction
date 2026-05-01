import pandas as pd
import sqlite3
import json

try:
    conn = sqlite3.connect('data/football.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(match_predictions)")
    cols = [r[1] for r in cursor.fetchall()]
    
    query_col = 'match_num'
    if query_col in cols:
        cursor.execute(f"SELECT * FROM match_predictions WHERE {query_col} LIKE '%周二002%' ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            print('\n--- Found in DB ---')
            row_dict = dict(zip(cols, row))
            print(row_dict)
            if 'raw_data' in row_dict:
                raw = json.loads(row_dict['raw_data'])
                if 'odds' in raw: print('\nRaw Odds:', json.dumps(raw['odds'], ensure_ascii=False, indent=2))
        else:
            print('\n--- Not found in DB ---')
except Exception as e:
    print('DB Error:', e)
