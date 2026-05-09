import os
import sys
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
reports_dir = os.path.join(project_root, 'data', 'reports')
os.makedirs(reports_dir, exist_ok=True)

from src.llm.predictor import LLMPredictor

def generate_detailed_report(target_date=None):
    try:
        # 改为读取全量结果文件
        all_matches_file = os.path.join(reports_dir, 'all_compared_matches.json')
        with open(all_matches_file, 'r', encoding='utf-8') as f:
            all_matches = json.load(f)
    except FileNotFoundError:
        print(f"找不到 {all_matches_file}，请先运行 run_post_mortem.py")
        return

    if not all_matches:
        print("没有记录需要分析。")
        return
        
    import datetime
    report_date = target_date if target_date else (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    predictor = LLMPredictor()
    
    total = len(all_matches)
    correct = sum(1 for m in all_matches if m['is_correct'])
    wrong = total - correct
    win_rate = (correct / total) * 100 if total > 0 else 0
    
    print(f"开始生成 {report_date} 详细报告，总计 {total} 场比赛...")
    
    # 区分MD报告
    md_file = f'detailed_post_mortem_report_{report_date}.md'
    report_content = f"# {report_date} 赛果详细复盘报告\n\n"
    report_content += f"## 1. 整体预测统计\n"
    report_content += f"- **总比对场次**: {total} 场\n"
    report_content += f"- **命中场次**: ✅ {correct} 场\n"
    report_content += f"- **错误场次**: ❌ {wrong} 场\n"
    report_content += f"- **整体胜率**: **{win_rate:.2f}%**\n\n"
    
    report_content += f"## 2. 逐场复盘明细\n\n"
    
    for i, m in enumerate(all_matches):
        status_icon = "✅ 命中" if m['is_correct'] else "❌ 错误"
        report_content += f"### [{m['match_num']}] {m['home_team']} vs {m['away_team']} - {status_icon}\n"
        report_content += f"- **真实比分**: {m['actual_score']} (打出: {m['actual_result']})\n"
        report_content += f"- **AI 当时推荐**: {m['ai_recommendation']}\n"
        report_content += f"- **AI 推荐理由**: {m['ai_reason']}\n"
        
        # 如果预测错误，单独调用一次大模型分析原因
        error_analysis = ""
        if not m['is_correct']:
            print(f"正在让大模型反思 {m['match_num']} 的错误原因...")
            
            # 为了让大模型分析冷门，我们需要把当时的亚盘和欧赔数据也传给它
            raw_data = m.get('raw_data', {})
            import json
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    raw_data = {}
            
            asian_odds = raw_data.get('asian_odds', {}).get('macau', {})
            asian_start = asian_odds.get('start', '未知')
            asian_live = asian_odds.get('live', '未知')
            
            prompt = f"""# Role: 严厉且专业的竞彩风控分析师
## Task:
我提供了一场预测失败的冷门（或赢球输盘）比赛数据，请你进行深度复盘分析。复盘重点必须放在盘口分析与盘口调度失误：当时系统是在哪个盘口判断环节读错了机构意图？这些错误如何沉淀成新的微观信号规则？

## 比赛信息:
- 对阵: [{m['match_num']}] {m['home_team']} vs {m['away_team']}
- 竞彩让球: {m.get('rangqiu', 0)}
- 澳门初盘: {asian_start}
- 澳门即时盘: {asian_live}
- 当时 AI 推荐: {m['ai_recommendation']}
- 当时 AI 理由: {m['ai_reason']}
- 最终真实比分: {m['actual_score']} (真实打出结果: {m['actual_result']})

## Output Requirement:
请用两段话进行极其尖锐的回复：
1. **盘口调度致死原因剖析**：一针见血指出系统在哪个盘口判断步骤错了，例如把阻上看成诱上、把退盘控热看成看衰、把欧赔实力方和亚赔让球方混为一谈、或该触发的微观信号漏判。请直接指出是哪种盘口陷阱发作，控制在 100 字以内。
2. **微观信号修正规则**：给出一条可以直接回灌到模型的规则修改建议，格式尽量接近“当出现XX盘口/水位/欧亚组合时，必须YY，防ZZ方向”，避免空泛建议。
"""
            try:
                response = predictor.client.chat.completions.create(
                    model=predictor.model,
                    messages=[
                        {"role": "system", "content": "你是资深的足彩风控分析师，擅长从失败中总结经验。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                
                # 调试信息
                print(f"API Response: {response.choices[0].message.content.strip()}")

                
                error_analysis = response.choices[0].message.content.strip()
                if not error_analysis:
                    error_analysis = "大模型未能返回分析结果"
                
                # 提取出分析内容，拼接到 MD 报告
                report_content += f"- **⚠️ 深度冷门复盘与优化建议**:\n"
                for line in error_analysis.split('\n'):
                    report_content += f"  > {line}\n"
                    
            except Exception as e:
                error_analysis = f"AI 分析失败 ({e})"
                report_content += f"- **⚠️ 深度冷门复盘与优化建议**: {error_analysis}\n"
        
        # 将结果存入字典中以便后续导出 CSV
        m['error_analysis'] = error_analysis
        
        report_content += "\n---\n\n"

    md_file = os.path.join(reports_dir, md_file)
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print(f"\n✅ 详细复盘报告已生成并保存至 {md_file}")
    
    # 追加导出为 CSV 文件
    import csv
    csv_file = os.path.join(reports_dir, 'detailed_post_mortem_report.csv')
    file_exists = os.path.isfile(csv_file)
    
    try:
        with open(csv_file, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # 如果文件不存在，先写入表头
            if not file_exists:
                writer.writerow(['日期', '比赛编号', '对阵', '盘口(让球)', '真实比分', '真实打出结果', 'AI 推荐', 'AI 理由', '是否命中', '深度冷门复盘与优化建议'])
            
            for m in all_matches:
                status = "命中" if m['is_correct'] else "错误"
                writer.writerow([
                    report_date,
                    m['match_num'],
                    f"{m['home_team']} vs {m['away_team']}",
                    m.get('rangqiu', 0),
                    m['actual_score'],
                    m['actual_result'],
                    m['ai_recommendation'],
                    m['ai_reason'],
                    status,
                    m.get('error_analysis', '')
                ])
        print(f"✅ CSV 数据已追加至 {csv_file}")
    except Exception as e:
        print(f"追加 CSV 失败: {e}")

if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    generate_detailed_report(target_date)
