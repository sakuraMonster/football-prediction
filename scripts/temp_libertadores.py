import sqlite3
import pandas as pd
conn = sqlite3.connect('data/football.db')
df2 = pd.read_sql("""
SELECT match_num, home_team, away_team, goals_pan, actual_goals, actual_score
FROM match_predictions
WHERE league LIKE '%解放者杯%'
ORDER BY match_time DESC LIMIT 10
""", conn)
print(df2)
