import sqlite3
import pandas as pd
conn = sqlite3.connect('data/football.db')
df = pd.read_sql("SELECT target_date, review_content FROM daily_reviews ORDER BY id DESC LIMIT 1", conn)
if not df.empty:
    print(f"=== Date: {df['target_date'].iloc[0]} ===")
    print(df['review_content'].iloc[0])
