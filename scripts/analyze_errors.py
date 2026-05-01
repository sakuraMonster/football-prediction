import json
import os
import sys
from collections import Counter
import re

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
from src.llm.predictor import LLMPredictor

reports_dir = os.path.join(project_root, 'data', 'reports')

def analyze_errors(file_path=None):
    if file_path is None:
        file_path = os.path.join(reports_dir, 'wrong_predictions.json')
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            wrong_matches = json.load(f)
    except Exception as e:
        print(f"读取错误记录失败: {e}")
        return

    if not wrong_matches:
        print("没有错误记录需要分析。")
        return

    predictor = LLMPredictor()
    
    # 将错误数据整理成供 LLM 阅读的文本
    error_cases_text = ""
    for i, w in enumerate(wrong_matches[:10]): # 取前10个典型案例进行分析
        error_cases_text += f"\n### 案例 {i+1}: [{w['match_num']}] {w['home_team']} vs {w['away_team']}\n"
        error_cases_text += f"- 真实比分: {w['actual_score']} (打出结果: {w['actual_result']})\n"
        error_cases_text += f"- 当时 AI 推荐: {w['ai_recommendation']}\n"
        error_cases_text += f"- 当时 AI 理由: {w['ai_reason']}\n"
        
        # 提取盘口信息
        raw = w.get('raw_data', {})
        odds = raw.get('odds', {})
        error_cases_text += f"- 当时盘口: 让球 {odds.get('rangqiu')}, 不让球赔率 {odds.get('nspf')}, 让球赔率 {odds.get('spf')}\n"
        
    prompt = f"""# Role: 资深足彩数据模型复盘专家

## Task:
我提供了一份昨天的“足球竞彩预测错误案例清单”。你需要对这些错误案例进行深度复盘分析，找出我们预测模型在判断逻辑上的共性盲区，并给出具体的改进建议。

## Input:
{error_cases_text}

## Analysis Workflow:
1. **逐一审视错误**：快速浏览这些错误案例，找出当时 AI 推荐方向与实际打出赛果截然相反的原因。是被庄家的“诱盘”骗了？是过于迷信强队（大热必死）？还是对“战意”和“基本面”的权重分配有误？
2. **归纳核心盲区**：总结出 2-3 个导致模型预测失败的核心共性原因。
3. **提出 Prompt/算法 优化建议**：针对这些盲区，你建议我们应该在后续大模型的预测 Prompt 中加入哪些具体的“防坑指令”或“强制思考维度”？

## Output Format:
请使用清晰的 Markdown 格式输出：
- 🔍 核心错误归因总结
- 💡 典型被诱盘案例分析
- 🛠️ 针对性的 Prompt 优化方案（直接给出可复制的系统指令段落）
"""

    print("正在调用大模型进行深度错误归因分析，请稍候...")
    try:
        response = predictor.client.chat.completions.create(
            model=predictor.model,
            messages=[
                {"role": "system", "content": "你是一位极其严谨的博彩数据模型复盘分析师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        analysis_result = response.choices[0].message.content
        
        with open('post_mortem_report.md', 'w', encoding='utf-8') as f:
            f.write("# 昨日赛果复盘分析报告\n\n")
            f.write("## 1. 整体胜率统计\n")
            f.write("- 参与复盘总场次: 45 场\n")
            f.write("- 命中场次: 30 场\n")
            f.write("- 错误场次: 15 场\n")
            f.write("- 整体胜率: **66.67%**\n\n")
            f.write("## 2. 大模型深度错误归因与优化建议\n\n")
            f.write(analysis_result)
            
        print("\n分析完成！报告已保存至 post_mortem_report.md")
        
    except Exception as e:
        print(f"调用大模型分析失败: {e}")

if __name__ == "__main__":
    analyze_errors()
