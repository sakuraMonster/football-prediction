from src.db.database import Database
db = Database()
preds = db.session.query(db.session.bind.tables['match_predictions'] if False else __import__('src.db.database', fromlist=['MatchPrediction']).MatchPrediction).all()
dates = set([p.match_time.strftime('%Y-%m-%d') for p in preds if p.match_time])
print("All Dates:", sorted(list(dates)))
for p in preds:
    if p.match_time and p.match_time.strftime('%Y-%m-%d') == '2026-03-29':
        print(f"2026-03-29 Match: {p.match_num}")
