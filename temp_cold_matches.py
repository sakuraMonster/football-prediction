import pandas as pd
import sqlite3
import json

conn = sqlite3.connect('data/football.db')
query = """
SELECT match_time, match_num, league, home_team, away_team, actual_result, actual_score, prediction_text, raw_data 
FROM match_predictions 
WHERE actual_score IS NOT NULL AND actual_score != 'None'
ORDER BY match_time DESC 
LIMIT 200
"""
df = pd.read_sql(query, conn)

print("提取详细AI预测理由...")
for _, row in df.iterrows():
    if row['match_num'] == '周二005' and row['home_team'] == '朴次茅斯':
        print(f"[{row['match_num']}] {row['home_team']} {row['actual_score']} {row['away_team']}")
        print(row['prediction_text'])
        break
