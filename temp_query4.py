import os
import sys
import json
import sqlite3

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
from src.llm.goals_predictor import GoalsPredictor

db_path = os.path.join(project_root, 'data', 'football.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT raw_data FROM match_predictions WHERE match_num = '周二006' ORDER BY created_at DESC LIMIT 1")
db_res = cursor.fetchone()

if db_res:
    raw_data = json.loads(db_res[0])
    match_data = raw_data.copy()
    match_data['goals_pan'] = '2/2.5'
    match_data['goals_diff_percent'] = 0.0
    match_data['goals_trend'] = '小'
    
    predictor = GoalsPredictor()
    goals_pred, _ = predictor.predict(match_data)
    with open('temp_report.txt', 'w', encoding='utf-8') as f:
        f.write(goals_pred)
else:
    with open('temp_report.txt', 'w', encoding='utf-8') as f:
        f.write("No DB record found for raw_data")
conn.close()
