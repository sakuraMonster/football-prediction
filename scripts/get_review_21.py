import sqlite3
import pandas as pd
conn = sqlite3.connect('data/football.db')
df = pd.read_sql("SELECT review_content FROM daily_reviews WHERE target_date = '2026-04-21'", conn)
if not df.empty:
    print(df['review_content'].iloc[0])
else:
    print("No review found")
