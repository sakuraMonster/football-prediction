import sqlite3
import pandas as pd
conn = sqlite3.connect('data/football.db')
print("Tables:", pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist())

df = pd.read_sql("SELECT * FROM match_predictions LIMIT 1", conn)
print("match_predictions columns:", df.columns.tolist())
