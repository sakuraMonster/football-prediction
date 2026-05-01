import json
import sys
sys.path.append('src')
from llm.predictor import LLMPredictor

def test():
    with open('data/today_matches.json', 'r', encoding='utf-8') as f:
        matches = json.load(f)
        if matches:
            pred = LLMPredictor()
            print('Testing Euro-Asian Divergence Detection...')
            for m in matches[:5]:
                print(f"\nMatch: {m.get('home_team')} vs {m.get('away_team')}")
                print(f"Odds: {m.get('odds', {}).get('nspf')}")
                print(f"Macau Start: {m.get('asian_odds', {}).get('macau', {}).get('start')}")
                res = pred._detect_euro_asian_divergence(m.get('odds', {}), m.get('asian_odds', {}))
                if res:
                    print(f"🚨 ALERT: {res}")
                else:
                    print("✅ No divergence detected.")

if __name__ == "__main__":
    test()
