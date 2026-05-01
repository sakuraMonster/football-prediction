import json
from src.llm.predictor import LLMPredictor

def run_custom_prediction():
    with open('temp_kelong.json', 'r', encoding='utf-8') as f:
        match_data = json.load(f)
    
    predictor = LLMPredictor()
    
    # 模拟外部传入的高强度体能消耗上下文
    # 我们在调用 _format_match_data 之前，手动在 match_data 中注入这一关键情报
    if 'recent_form' not in match_data:
        match_data['recent_form'] = {}
        
    custom_injury_text = match_data['recent_form'].get('injuries', '')
    if custom_injury_text:
        custom_injury_text += "\n"
    custom_injury_text += "🚨【重要赛程与体能情报】🚨：客队勒沃库森在刚刚过去的周中与斯图加特进行了一场德国杯（DFB-Pokal）的极高强度恶战，主力球员体能消耗极大！本场比赛面临严重的体能危机和可能的轮换！"
    
    match_data['recent_form']['injuries'] = custom_injury_text
    
    print("开始预测，已注入周中德国杯消耗情报...")
    result = predictor.predict(match_data)
    print("\n\n" + "="*50)
    print(result)
    print("="*50)

if __name__ == "__main__":
    run_custom_prediction()
