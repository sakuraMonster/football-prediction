import os
import sys
import json
import logging
from datetime import datetime, timedelta
import argparse

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
reports_dir = os.path.join(project_root, 'data', 'reports')
os.makedirs(reports_dir, exist_ok=True)

from src.crawler.jclq_crawler import JclqCrawler
from src.db.database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_bball_detailed_report(target_date):
    """
    读取比较结果，生成详细的篮球复盘报告并追加到 CSV 中。
    """
    import csv
    import re
    
    compared_file = os.path.join(reports_dir, 'bball_all_compared_matches.json')
    csv_file = os.path.join(reports_dir, 'detailed_bball_post_mortem_report.csv')
    
    if not os.path.exists(compared_file):
        logger.error(f"未找到比对文件: {compared_file}")
        return
        
    with open(compared_file, 'r', encoding='utf-8') as f:
        matches = json.load(f)
        
    if not matches:
        logger.info("没有篮球比对数据可供生成报告。")
        return
        
    # 定义 CSV 表头
    headers = [
        "Date", "Match Num", "Match", "Rangfen", "Total Score Base", "Score", 
        "Actual Result", "AI Recommendation", "AI Reason", "Hit Status", "AI Reflection"
    ]
    
    # 检查文件是否存在，如果不存在则写入表头
    file_exists = os.path.exists(csv_file)
    
    with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
            
        for m in matches:
            actual_res = f"({m['rangfen']}) {m['actual_rfsf_result']} | ({m['yszf']}) {m['actual_dxf_result']}"
            
            # 简化的AI反思（为了脚本运行速度，这里用默认文字代替调用LLM）
            # 后续可引入专门针对篮球的 LLM 错误归因
            ai_reflection = "暂无"
            if not m['is_correct']:
                ai_reflection = "预测错误。需复盘比赛过程、体能消耗或临场伤病情况。"
            
            writer.writerow({
                "Date": target_date,
                "Match Num": m['match_num'],
                "Match": f"{m['home_team']} vs {m['away_team']}",
                "Rangfen": m['rangfen'],
                "Total Score Base": m['yszf'],
                "Score": m['actual_score'],
                "Actual Result": actual_res,
                "AI Recommendation": m['ai_recommendation'],
                "AI Reason": m.get('ai_reason', '暂无').replace('\n', ' '),
                "Hit Status": "命中" if m['is_correct'] else "错误",
                "AI Reflection": ai_reflection
            })
            
    logger.info(f"详细篮球复盘报告已追加至: {csv_file}")

def run_bball_post_mortem(target_date=None):
    if not target_date:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
    logger.info(f"开始执行篮球赛后复盘分析: {target_date}")
    
    # 1. 抓取昨日实际赛果
    crawler = JclqCrawler()
    actual_results = crawler.fetch_match_results(target_date)
    
    if not actual_results:
        logger.warning(f"未能获取 {target_date} 的篮球赛果数据。")
        return
        
    # 2. 从数据库查询预测记录
    db = Database()
    from src.db.database import BasketballPrediction
    try:
        # 查询 target_date 及其前后一天的数据（篮球有跨天结算的可能，特别是美国比赛在北京时间次日）
        prev_date = (datetime.strptime(target_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        next_date = (datetime.strptime(target_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        
        # 提取全表数据在内存中过滤，因为 Database 类尚未提供 get_bball_predictions_by_date_range 方法
        predictions = db.session.query(BasketballPrediction).all()
        
        # 过滤包含该日期的记录
        filtered_preds = []
        for p in predictions:
            if not p.match_time:
                continue
            
            # match_time 可能是 datetime 对象，也可能是字符串
            m_time_str = p.match_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(p.match_time, datetime) else str(p.match_time)
            c_time_str = p.created_at.strftime('%Y-%m-%d %H:%M:%S') if p.created_at and isinstance(p.created_at, datetime) else str(p.created_at) if p.created_at else ""
            
            # 匹配逻辑：比赛时间在前后一天内，或者创建时间在目标日期
            if prev_date in m_time_str or target_date in m_time_str or next_date in m_time_str or target_date in c_time_str:
                filtered_preds.append(p)
        predictions = filtered_preds
        
    except Exception as e:
        logger.error(f"查询篮球预测数据失败: {e}")
        predictions = []
    
    if not predictions:
        logger.warning(f"数据库中没有找到这段时间的篮球预测数据。")
        return
        
    # 转换预测数据格式
    pred_dict = {}
    for p in predictions:
        # 使用 match_num 作为主要匹配键，如果为空则使用对阵
        key = p.match_num if p.match_num else f"{p.home_team}_{p.away_team}"
        pred_dict[key] = p

    # 3. 对比结果
    total_matches = 0
    correct_count = 0
    compared_results = []
    
    for actual in actual_results:
        match_num = actual['match_num']
        key = match_num if match_num else f"{actual['home_team']}_{actual['away_team']}"
        
        pred = pred_dict.get(key)
        if not pred:
            # 尝试模糊匹配队名
            for k, p in pred_dict.items():
                if actual['home_team'] in p.home_team and actual['away_team'] in p.away_team:
                    pred = p
                    break
                    
        if not pred:
            continue
            
        total_matches += 1
        
        # 提取AI推荐内容
        recommendation = ""
        reason = ""
        try:
            from src.llm.bball_predictor import BBallPredictor
            details = BBallPredictor.parse_prediction_details(pred.prediction_text)
            rec_sf = details.get('recommendation', '')
            rec_dxf = details.get('dxf_recommendation', '')
            reason = details.get('reason', '')
            
            # 合并让分和大小分推荐以便判断
            recommendation = f"{rec_sf} | (总分) {rec_dxf}"
                
        except Exception as e:
            logger.error(f"解析篮球预测文本失败: {e}")
            recommendation = "暂无"
            reason = "暂无"
        
        # 判断命中逻辑
        is_correct = False
        import re
        
        # 清理推荐文本中的括号解释
        clean_rec = re.sub(r'\(.*?\)', '', recommendation)
        clean_rec = re.sub(r'（.*?）', '', clean_rec)
        clean_rec = re.sub(r'（[^）]*$', '', clean_rec)
        clean_rec = re.sub(r'\([^)]*$', '', clean_rec)
        
        rec_options = [opt.strip() for opt in re.split(r'[/|]', clean_rec) if opt.strip()]
        
        # 篮球通常匹配：主胜、客胜、让分主胜、让分客胜、大分、小分
        actual_sf = actual['sf_result']
        actual_rfsf = actual['rfsf_result']
        actual_dxf = actual['dxf_result']
        
        for opt in rec_options:
            # 大小分匹配
            if '大分' in opt or '小分' in opt:
                if '大分' in opt and '大分' in actual_dxf:
                    is_correct = True
                    break
                if '小分' in opt and '小分' in actual_dxf:
                    is_correct = True
                    break
            # 让分胜负匹配
            elif '让分' in opt or '让' in opt:
                # 预测包含主胜/让胜/让分主胜
                if ('主胜' in opt or '让胜' in opt) and '主胜' in actual_rfsf:
                    is_correct = True
                    break
                # 预测包含客胜/让负/主负/让分主负/让分客胜
                if ('客胜' in opt or '主负' in opt or '让负' in opt) and '客胜' in actual_rfsf:
                    is_correct = True
                    break
            # 不让分胜负匹配
            else:
                if '主胜' in opt and '主胜' in actual_sf:
                    is_correct = True
                    break
                if '客胜' in opt and '客胜' in actual_sf:
                    is_correct = True
                    break
                    
        if is_correct:
            correct_count += 1
            
        compared_results.append({
            "match_num": match_num,
            "home_team": actual['home_team'],
            "away_team": actual['away_team'],
            "actual_score": actual['score'],
            "rangfen": actual['rangfen'],
            "yszf": actual['yszf'],
            "actual_sf_result": actual_sf,
            "actual_rfsf_result": actual_rfsf,
            "actual_dxf_result": actual_dxf,
            "ai_recommendation": recommendation,
            "ai_reason": reason,
            "is_correct": is_correct
        })
        
        # 更新数据库
        try:
            pred.actual_score = actual['score']
            pred.is_correct = is_correct
            db.session.commit()
        except Exception as e:
            logger.error(f"更新篮球数据库失败: {e}")
            db.session.rollback()
            
    # 保存 JSON
    with open(os.path.join(reports_dir, 'bball_all_compared_matches.json'), 'w', encoding='utf-8') as f:
        json.dump(compared_results, f, ensure_ascii=False, indent=2)
        
    logger.info("="*50)
    logger.info(f"篮球复盘日期: {target_date}")
    logger.info(f"总计可对比场次: {total_matches}")
    if total_matches > 0:
        hit_rate = (correct_count / total_matches) * 100
        logger.info(f"命中场次: {correct_count}")
        logger.info(f"错误场次: {total_matches - correct_count}")
        logger.info(f"整体胜率: {hit_rate:.2f}%")
    logger.info("="*50)
    
    # 生成 CSV
    generate_bball_detailed_report(target_date)

if __name__ == "__main__":
    target_date = None
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    run_bball_post_mortem(target_date)