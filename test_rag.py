import json
import os
import sys
sys.path.append('src')
from llm.predictor import LLMPredictor

def create_mock_error_db():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    error_db_dir = os.path.join(base_dir, 'data', 'knowledge_base', 'errors')
    os.makedirs(error_db_dir, exist_ok=True)
    
    # 伪造一个前几天的错题（例如：欧罗巴联赛，平半盘诱导）
    mock_errors = [
        {
            "match_num": "周四005",
            "home_team": "布拉加",
            "away_team": "弗赖堡",
            "league": "欧罗巴",
            "asian_start": "平手/半球",
            "actual_result": "胜/让胜",
            "ai_reason": "主队水位从0.77飙升至1.01，盘口未变，这是机构在真实看衰主队，主场让球无力，客队必定不败。",
            "raw_data": {"league": "欧罗巴"}
        }
    ]
    
    with open(os.path.join(error_db_dir, 'errors_2026-04-30.json'), 'w', encoding='utf-8') as f:
        json.dump(mock_errors, f, ensure_ascii=False, indent=2)
    print("已生成测试用的历史错题库: errors_2026-04-30.json")

def test_recall():
    # 构造一个和错题高度相似的假比赛数据进行测试
    mock_match_data = {
        "league": "欧罗巴",
        "home_team": "罗马",
        "away_team": "勒沃库森",
        "odds": {"rangqiu": "-1"},
        "asian_odds": {"macau": {"start": "1.00 平手/半球 0.80"}}
    }
    
    pred = LLMPredictor()
    # predictor 中现在用于获取盘型的是 _classify_handicap，不过它在 v3 稍微调整了逻辑。
    # 既然之前的测试没召回是因为 handicap_label 为空，我们直接给它一个模拟的 label 进行测试
    handicap_label = "平手/半球"
    print(f"Handicap Label: {handicap_label}")
    
    print("\n--- 开始测试 RAG 召回机制 ---")
    warning = pred._recall_similar_errors(mock_match_data, handicap_label)
    if warning:
        print("✅ 成功召回相似错题！注入的 Prompt 如下：\n")
        print(warning)
    else:
        print("❌ 未能召回错题。")

if __name__ == "__main__":
    create_mock_error_db()
    test_recall()
