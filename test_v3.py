import json
import sys
sys.path.append('src')
from llm.predictor import LLMPredictor

def test_v3_workflow():
    with open('data/today_matches.json', 'r', encoding='utf-8') as f:
        matches = json.load(f)
        if matches:
            # 取第一场比赛测试
            match = matches[0]
            print(f"\n=============================================")
            print(f"Testing V3 Workflow: {match.get('home_team')} vs {match.get('away_team')}")
            print(f"=============================================")
            
            pred = LLMPredictor()
            res, period = pred.predict(match)
            print("\n>>> Final Result:\n")
            print(res)

if __name__ == "__main__":
    test_v3_workflow()
