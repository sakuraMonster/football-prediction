import sqlite3
conn = sqlite3.connect('data/football.db')
cur = conn.cursor()
cur.execute("SELECT review_content FROM daily_reviews WHERE target_date = '2026-04-25'")
res = cur.fetchone()
if res:
    print(res[0])
else:
    print("No review found for 2026-04-25")
conn.close()
