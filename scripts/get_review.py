import sqlite3
import pandas as pd
conn = sqlite3.connect('data/football.db')
df = pd.read_sql("SELECT target_date, review_content FROM daily_reviews ORDER BY id DESC LIMIT 1", conn)
if not df.empty:
    for _, row in df.iterrows():
        print(f"=== Date: {row['target_date']} ===")
        content = row['review_content']
        if content:
            print(content)
        print('...\n')
