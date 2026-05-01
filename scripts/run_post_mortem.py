import os
import sys
import datetime
from sqlalchemy import create_engine, MetaData, Table

# 添加根目录到环境变量
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
reports_dir = os.path.join(project_root, 'data', 'reports')
os.makedirs(reports_dir, exist_ok=True)

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.db.database import Database
from src.llm.predictor import LLMPredictor

def calculate_actual_result(score_str, rangqiu_str):
    """
    根据比分 '2:1' 和 让球数 '-1' 计算实际的胜平负和让球胜平负
    返回: (胜平负结果, 让球胜平负结果)
    """
    try:
        home_score, away_score = map(int, score_str.split(':'))
        rq = int(float(rangqiu_str))
        
        # 不让球
        if home_score > away_score:
            nspf = "胜"
        elif home_score == away_score:
            nspf = "平"
        else:
            nspf = "负"
            
        # 让球
        adjusted_home = home_score + rq
        if adjusted_home > away_score:
            spf = "让胜"
        elif adjusted_home == away_score:
            spf = "让平"
        else:
            spf = "让负"
            
        return nspf, spf
    except Exception as e:
        print(f"解析比分出错: {score_str}, {e}")
        return None, None


def handicap_type(rangqiu_str, asian_odds=None):
    """将盘口转换为盘型分类。优先使用亚指实际盘口文本，fallback到竞彩让球数。"""
    handicap_text = ""
    if asian_odds:
        macau_start = asian_odds.get('macau', {}).get('start', '')
        if macau_start and '|' in macau_start:
            handicap_text = macau_start.split('|')[1].strip()
    
    if not handicap_text:
        try:
            rq = int(float(rangqiu_str))
        except:
            return "未知"
        rq = abs(rq)
        if rq == 0: return "平手"
        if rq == 1: return "平半~半球"
        if 2 <= rq <= 3: return "半一~一球"
        if 4 <= rq <= 6: return "一球/球半~球半"
        return "深盘"
    
    # 从亚指文本提取盘型（先检查"受"字变体，再检查主让变体）
    ht = handicap_text.replace(' ', '')
    if '受平手/半球' in ht:
        return "受平半"
    if '平手/半球' in ht or '平半' in ht:
        return "平半"
    if '平手' in ht:
        return "平手"
    if '受半球/一球' in ht:
        return "受半一"
    if '半球/一球' in ht or '半一' in ht:
        return "半一"
    if '受一球/球半' in ht:
        return "受一球/球半"
    if '一球/球半' in ht:
        return "一球/球半"
    if '受半球' in ht:
        return "受半球"
    if '半球' in ht and '球半' not in ht:
        return "半球"
    if '受一球' in ht:
        return "受一球"
    if '一球' in ht:
        return "一球"
    if '受球半' in ht:
        return "受球半"
    if '球半' in ht:
        return "球半"
    if '受两球' in ht:
        return "受两球"
    if '两球' in ht:
        return "两球"
    if '两球半' in ht:
        return "两球半+"
    return ht[:6]


def compute_accuracy_report(target_date=None):
    """
    程序化计算指定日期的预测准确率报告。
    从数据库直接读取预测和赛果，逐场计算命中情况，返回结构化报告。
    同时将 is_correct 写回数据库。
    
    返回:
        dict: {
            "date": str,
            "overall": {"total": int, "correct_nspf": int, "correct_spf": int, "correct_bqc": int},
            "by_league": {league: {"total": int, "correct_nspf": int}},
            "by_handicap": {htype: {"total": int, "correct_nspf": int}},
            "matches": [{"match_num": str, "home": str, "away": str, "pred_nspf": str, 
                         "pred_spf": str, "actual_score": str, "actual_nspf": str, 
                         "actual_spf": str, "is_correct_nspf": bool, "is_correct_spf": bool,
                         "league": str, "asian_start": str, "asian_live": str, "reason": str}]
        }
    """
    import json, re
    from collections import defaultdict
    from sqlalchemy import text
    
    if target_date is None:
        target_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 日周期窗口: 目标日 12:00:00 ~ 次日 12:00:00
    window_start = f"{target_date} 12:00:00"
    next_day = (datetime.datetime.strptime(target_date, '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    window_end = f"{next_day} 12:00:00"
    batch_label = f"{target_date} 12:00 ~ {next_day} 12:00"
    
    db = Database()
    
    query = text("""
        SELECT m1.* 
        FROM match_predictions m1
        JOIN (
            SELECT match_num, DATE(match_time) as m_date,
                   COALESCE(
                     MAX(CASE WHEN prediction_period = 'repredicted' THEN id END),
                     MAX(CASE WHEN prediction_period NOT IN ('historical', 'repredicted') THEN id END),
                     MAX(id)
                   ) as max_id 
            FROM match_predictions 
            WHERE match_time >= :window_start AND match_time < :window_end
              AND prediction_period != 'historical'
            GROUP BY match_num, DATE(match_time)
        ) m2 ON m1.id = m2.max_id
        WHERE m1.actual_score IS NOT NULL AND m1.actual_score != '' AND m1.actual_score != '暂无'
          AND m1.prediction_text IS NOT NULL AND m1.prediction_text != ''
        ORDER BY m1.match_time
    """)
    params = {"window_start": window_start, "window_end": window_end}
    
    try:
        predictions = db.session.execute(query, params).fetchall()
    except Exception as e:
        print(f"查询预测记录失败: {e}")
        db.close()
        return None
    
    meta = MetaData()
    meta.reflect(bind=db.engine)
    pred_table = meta.tables['match_predictions']
    columns = [c.name for c in pred_table.columns]
    pred_dicts = [dict(zip(columns, p)) for p in predictions]
    
    report = {
        "date": target_date,
        "batch_label": batch_label,
        "overall": {"total": 0, "correct_nspf": 0, "correct_spf": 0, "correct_bqc": 0},
        "by_league": defaultdict(lambda: {"total": 0, "correct_nspf": 0}),
        "by_handicap": defaultdict(lambda: {"total": 0, "correct_nspf": 0}),
        "matches": []
    }
    
    bqc_map = {
        '胜胜': '3-3', '胜平': '3-1', '胜负': '3-0',
        '平胜': '1-3', '平平': '1-1', '平负': '1-0',
        '负胜': '0-3', '负平': '0-1', '负负': '0-0'
    }
    
    update_count = 0
    
    for pred in pred_dicts:
        actual_score = pred.get('actual_score', '')
        if not actual_score or actual_score in ('暂无', '', None):
            continue
        
        raw_data = pred.get('raw_data', {})
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except:
                raw_data = {}
        
        odds = raw_data.get('odds', {})
        rangqiu = odds.get('rangqiu', '0')
        
        actual_nspf, actual_spf = calculate_actual_result(actual_score, rangqiu)
        if not actual_nspf:
            continue
        
        # Parse prediction
        pred_text = pred.get('prediction_text', '')
        details = LLMPredictor.parse_prediction_details(pred_text)
        pred_nspf = details.get('recommendation_nspf', '')
        pred_rq = details.get('recommendation_rq', '')
        reason = details.get('reason', '')
        
        # Get asian odds
        full_asian = raw_data.get('asian_odds', {})
        asian_odds = full_asian.get('macau', {})
        asian_start = asian_odds.get('start', '')
        asian_live = asian_odds.get('live', '')
        
        # Determine NSPF correctness
        is_correct_nspf = False
        if pred_nspf and pred_nspf != '暂无':
            is_correct_nspf = actual_nspf in pred_nspf
        
        # Determine SPF correctness
        is_correct_spf = False
        if pred_rq and pred_rq != '暂无':
            is_correct_spf = actual_spf in pred_rq
        
        # Determine BQC correctness
        is_correct_bqc = False
        actual_bqc = pred.get('actual_bqc', '')
        if actual_bqc:
            for line in pred_text.split('\n'):
                for bqc_cn, bqc_code in bqc_map.items():
                    if bqc_cn in line and bqc_code == actual_bqc:
                        is_correct_bqc = True
                        break
        
        htype = handicap_type(rangqiu, full_asian)
        league = pred.get('league', '')
        
        report["overall"]["total"] += 1
        if is_correct_nspf:
            report["overall"]["correct_nspf"] += 1
        if is_correct_spf:
            report["overall"]["correct_spf"] += 1
        if is_correct_bqc:
            report["overall"]["correct_bqc"] += 1
        
        report["by_league"][league]["total"] += 1
        if is_correct_nspf:
            report["by_league"][league]["correct_nspf"] += 1
        
        report["by_handicap"][htype]["total"] += 1
        if is_correct_nspf:
            report["by_handicap"][htype]["correct_nspf"] += 1
        
        report["matches"].append({
            "match_num": pred.get('match_num', ''),
            "home": pred.get('home_team', ''),
            "away": pred.get('away_team', ''),
            "league": league,
            "match_time": str(pred.get('match_time', '')),
            "pred_nspf": pred_nspf if pred_nspf != '暂无' else '无',
            "pred_spf": pred_rq if pred_rq != '暂无' else '无',
            "actual_score": actual_score,
            "actual_nspf": actual_nspf,
            "actual_spf": actual_spf,
            "actual_bqc": actual_bqc,
            "is_correct_nspf": is_correct_nspf,
            "is_correct_spf": is_correct_spf,
            "is_correct_bqc": is_correct_bqc,
            "asian_start": asian_start,
            "asian_live": asian_live,
            "reason": reason,
            "pred_id": pred.get('id')
        })
        
        # Write is_correct back to DB (overall)
        is_correct_overall = is_correct_nspf or is_correct_spf
        try:
            db.session.execute(
                text("UPDATE match_predictions SET is_correct = :ic, actual_result = :ar WHERE id = :id"),
                {"ic": is_correct_overall, "ar": actual_nspf, "id": pred['id']}
            )
            update_count += 1
        except:
            pass
    
    # Commit all DB writes
    try:
        db.session.commit()
        print(f"[DB] is_correct 已写入 {update_count} 条记录")
    except:
        pass
    
    db.close()
    
    # Print summary
    t = report["overall"]["total"]
    if t > 0:
        print(f"\n========== {target_date} 准确率报告 ==========")
        print(f"总场次: {t}")
        print(f"不让球命中: {report['overall']['correct_nspf']}/{t} = {report['overall']['correct_nspf']/t*100:.1f}%")
        print(f"让球命中: {report['overall']['correct_spf']}/{t} = {report['overall']['correct_spf']/t*100:.1f}%")
        print(f"\n按联赛:")
        for lg, st in sorted(report["by_league"].items(), key=lambda x: x[1]['total'], reverse=True):
            if st['total'] > 0:
                print(f"  {lg}: {st['correct_nspf']}/{st['total']} = {st['correct_nspf']/st['total']*100:.0f}%")
        print(f"\n按盘型:")
        for ht, st in sorted(report["by_handicap"].items(), key=lambda x: x[1]['total'], reverse=True):
            if st['total'] > 0:
                print(f"  {ht}: {st['correct_nspf']}/{st['total']} = {st['correct_nspf']/st['total']*100:.0f}%")
    
    return report

def do_post_mortem(target_date=None):
    # 1. 确定复盘的日期
    if target_date:
        yesterday = target_date
    else:
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"========== 开始复盘 {yesterday} 的比赛 ==========")
    
    # 2. 拉取昨日赛果
    crawler = JingcaiCrawler()
    results = crawler.fetch_match_results(yesterday)
    print(f"从 500 网获取到 {len(results)} 场 {yesterday} 的比赛赛果。")
    if not results:
        print("未获取到赛果，可能昨天没有比赛，或500网数据未更新。")
        return
        
    # 3. 获取数据库中的预测记录
    from sqlalchemy import text
    db = Database()
    
    # 查询昨天及今天创建的预测，或者比赛时间包含昨天或今天的预测，缩小范围
    # 也可以直接全表查询，但在代码中通过日期或球队名进行精确过滤
    try:
        # 修改拉取逻辑：针对每一场比赛（通过 match_num 分组），只拉取其最新的一条预测记录进行比对，防止同一场比赛多次预测导致重复拉取或提取旧数据
        query = text("""
            SELECT m1.* 
            FROM match_predictions m1
            JOIN (
                SELECT match_num, DATE(match_time) as m_date, MAX(id) as max_id 
                FROM match_predictions 
                WHERE DATE(match_time) BETWEEN :prev AND :next
                   OR DATE(created_at) BETWEEN :prev AND :next
                GROUP BY match_num, DATE(match_time)
            ) m2 ON m1.id = m2.max_id
            ORDER BY m1.created_at DESC
        """)
        prev_date = (datetime.datetime.strptime(yesterday, '%Y-%m-%d') - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        next_date = (datetime.datetime.strptime(yesterday, '%Y-%m-%d') + datetime.timedelta(days=2)).strftime('%Y-%m-%d')
        predictions = db.session.execute(query, {"prev": prev_date, "next": next_date}).fetchall()   
    except Exception as e:
        print(f"查询数据库预测记录失败: {e}")
        db.close()
        return
    # 获取所有的列名
    meta = MetaData()
    meta.reflect(bind=db.engine)
    pred_table = meta.tables['match_predictions']
    columns = [c.name for c in pred_table.columns]
    
    # 转换为字典列表
    pred_dicts = [dict(zip(columns, p)) for p in predictions]
    
    # 过滤出符合目标日期的预测记录（防止跨周同 match_num 的比赛被错误匹配）
    # 匹配条件：数据库预测记录的 home_team / away_team 与爬虫结果中的球队匹配，或者日期匹配
    # 这里我们采用更严谨的方式：先对预测记录按照 match_num 进行分组，然后在循环里比对球队名字
    
    # 去重：同一场比赛只取最新的一次预测
    latest_preds = {}
    for p in pred_dicts:
        fix_id = p['fixture_id']
        if fix_id not in latest_preds:
            latest_preds[fix_id] = p
            
    print(f"从数据库获取到 {len(latest_preds)} 场不同的比赛预测记录。")
    
    total_compared = 0
    correct_count = 0
    wrong_matches = []
    
    for fix_id, pred in latest_preds.items():
        match_num = pred['match_num']
        
        # 看看昨天的赛果里有没有这场
        if match_num in results:
            actual_res = results[match_num]
            
            # 核心修复：防止前几周同编号（如“周二001”）的比赛被错误匹配，需要验证球队名字的相似度或匹配度
            # 由于抓取的球队名与API获取的可能略有差异（如“墨尔本城” vs “墨城”），我们可以通过检查前两个字是否包含来模糊匹配
            actual_home = actual_res.get('home_team', '')
            actual_away = actual_res.get('away_team', '')
            pred_home = pred.get('home_team', '')
            pred_away = pred.get('away_team', '')
            
            # 球队匹配逻辑：至少主队或客队的名字互相有包含关系，或者比赛时间在前后两天内
            team_match = False
            if actual_home and pred_home and (actual_home[:2] in pred_home or pred_home[:2] in actual_home):
                team_match = True
            if actual_away and pred_away and (actual_away[:2] in pred_away or pred_away[:2] in actual_away):
                team_match = True
                
            # 时间匹配逻辑：
            time_match = False
            m_time = pred.get('match_time')
            m_time_str = m_time.strftime('%Y-%m-%d') if m_time and isinstance(m_time, datetime.datetime) else str(m_time) if m_time else ""
            c_time = pred.get('created_at')
            c_time_str = c_time.strftime('%Y-%m-%d') if c_time and isinstance(c_time, datetime.datetime) else str(c_time) if c_time else ""
            
            prev_date = (datetime.datetime.strptime(yesterday, '%Y-%m-%d') - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            next_date = (datetime.datetime.strptime(yesterday, '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            
            if yesterday in m_time_str or prev_date in m_time_str or next_date in m_time_str:
                time_match = True
            elif yesterday in c_time_str or prev_date in c_time_str:
                time_match = True
                
            if not (team_match or time_match):
                continue
                
            actual_score = actual_res['score']
            raw_data = pred.get('raw_data', {})
            import json
            if isinstance(raw_data, str):
                try:
                    import json
                    raw_data = json.loads(raw_data)
                except:
                    raw_data = {}
                    
            odds = raw_data.get('odds', {})
            rangqiu = odds.get('rangqiu', '0')
            
            actual_nspf, actual_spf = calculate_actual_result(actual_score, rangqiu)
            actual_bqc = actual_res.get('bqc_result')
            
            if not actual_nspf:
                continue
                
            # 更新数据库赛果
            try:
                db.update_actual_result(pred['fixture_id'], actual_score, actual_bqc)
            except Exception as e:
                print(f"更新数据库赛果失败: {e}")
                
            # 解析 LLM 当时的预测推荐
            prediction_text = pred.get('prediction_text', '')
            details = LLMPredictor.parse_prediction_details(prediction_text)
            recommendation = details.get('recommendation', '')
            reason = details.get('reason', '')
            
            # 判断是否命中
            # 简单的包含逻辑：如果 AI 推荐“胜”，且真实打出“胜”，则算命中。
            # 如果是双选“胜/平”，只要实际打出其中一个就算命中。
            is_correct = False
            
            import re
            
            # 修复AI幻觉导致的假阳性命中
            # 1. 修复AI在让球选项中省略“让”字的情况，如“(让球 +1) 平 / 负”
            parts = recommendation.split('|')
            corrected_parts = []
            for part in parts:
                if '让球' in part and '不让球' not in part:
                    # 仅匹配独立的胜平负，避免匹配到“净胜”等词
                    part = re.sub(r'(?<=[/\s)>])(胜|平|负)(?=[/\s(<|（]|等|$)', r'让\1', part)
                    # 补充处理可能在字符串开头的情况
                    part = re.sub(r'^(胜|平|负)(?=[/\s(<|（]|等|$)', r'让\1', part)
                corrected_parts.append(part)
            corrected_rec = '|'.join(corrected_parts)
            
            # 2. 如果AI输出“让胜”但上下文写了“客队大胜”或“客胜”，说明AI把让球方搞反了（真实意图是让负）
            if '让胜' in corrected_rec and ('客胜' in corrected_rec or '客队大胜' in corrected_rec or '客队赢' in corrected_rec or '客赢' in corrected_rec):
                corrected_rec = corrected_rec.replace('让胜', '让负')
            if '让负' in corrected_rec and ('主胜' in corrected_rec or '主队大胜' in corrected_rec or '主队赢' in corrected_rec or '主赢' in corrected_rec):
                corrected_rec = corrected_rec.replace('让负', '让胜')
            
            # 清理推荐文本中的多余字符，防止干扰匹配
            import re
            # 提取括号外的主要推荐内容，忽略括号内如“(让球 客队-1) 让胜（客队大胜）”里的解释
            # 把括号和里面的内容去掉，只保留核心结果词
            clean_rec = re.sub(r'\(.*?\)', '', corrected_rec)
            clean_rec = re.sub(r'（.*?）', '', clean_rec)
            clean_rec = re.sub(r'（[^）]*$', '', clean_rec) # 处理未闭合的中文左括号
            clean_rec = re.sub(r'\([^)]*$', '', clean_rec) # 处理未闭合的英文左括号
            clean_rec = clean_rec.replace('主', '').replace('客', '').replace('让球', '让')
            
            # 严格匹配与逻辑一致性校验
            # 使用 split('/') 或 '|' 处理双选的情况
            rec_options = [opt.strip() for opt in re.split(r'[/|]', clean_rec) if opt.strip()]
            
            ai_nspf_opts = set()
            ai_spf_opts = set()
            ai_bqc_opts = set()
            
            # 半全场映射表
            bqc_map = {
                '胜胜': '3-3', '胜平': '3-1', '胜负': '3-0',
                '平胜': '1-3', '平平': '1-1', '平负': '1-0',
                '负胜': '0-3', '负平': '0-1', '负负': '0-0'
            }
            
            for opt in rec_options:
                bqc_matched = False
                for key, val in bqc_map.items():
                    if key in opt:
                        ai_bqc_opts.add(val)
                        bqc_matched = True
                
                if bqc_matched:
                    continue
                    
                if '让' not in opt:
                    if '胜' in opt: ai_nspf_opts.add('胜')
                    if '平' in opt: ai_nspf_opts.add('平')
                    if '负' in opt: ai_nspf_opts.add('负')
                else:
                    if '让胜' in opt: ai_spf_opts.add('让胜')
                    if '让平' in opt: ai_spf_opts.add('让平')
                    if '让负' in opt: ai_spf_opts.add('让负')
                    
            # 过滤掉AI幻觉产生的自相矛盾的让球选项
            # 例如 AI 预测不让球是“平/胜”，但让球(+1)却写了“让平”(这意味着客胜1球)，这显然是大模型的概念幻觉
            if ai_nspf_opts:
                try:
                    rq = int(float(rangqiu))
                    possible_spfs = set()
                    for nspf in ai_nspf_opts:
                        if nspf == '胜':
                            if rq >= 0: possible_spfs.add('让胜')
                            elif rq == -1: possible_spfs.update(['让胜', '让平'])
                            else: possible_spfs.update(['让胜', '让平', '让负'])
                        elif nspf == '平':
                            if rq > 0: possible_spfs.add('让胜')
                            elif rq == 0: possible_spfs.add('让平')
                            elif rq < 0: possible_spfs.add('让负')
                        elif nspf == '负':
                            if rq <= 0: possible_spfs.add('让负')
                            elif rq == 1: possible_spfs.update(['让平', '让负'])
                            else: possible_spfs.update(['让胜', '让平', '让负'])
                    
                    # 仅保留在逻辑上可能出现的让球选项
                    ai_spf_opts = {opt for opt in ai_spf_opts if opt in possible_spfs}
                except Exception:
                    pass
            
            # 最终判断是否命中
            is_correct = False
            if actual_nspf in ai_nspf_opts:
                is_correct = True
            if actual_spf in ai_spf_opts:
                is_correct = True
            if actual_bqc and actual_bqc in ai_bqc_opts:
                is_correct = True
                
            if is_correct:
                correct_count += 1
            else:
                wrong_matches.append({
                    "match_num": match_num,
                    "home_team": pred['home_team'],
                    "away_team": pred['away_team'],
                    "rangqiu": rangqiu,
                    "actual_score": actual_score,
                    "actual_result": f"{actual_nspf}/{actual_spf}",
                    "ai_recommendation": recommendation,
                    "ai_reason": reason,
                    "raw_data": raw_data
                })
                
            total_compared += 1
            
            # 将每一场的结果都保存在列表中，用于最后生成完整报告
            if not hasattr(do_post_mortem, "all_matches_report"):
                do_post_mortem.all_matches_report = []
                
            do_post_mortem.all_matches_report.append({
                "match_num": match_num,
                "home_team": pred['home_team'],
                "away_team": pred['away_team'],
                "rangqiu": rangqiu,
                "actual_score": actual_score,
                "actual_result": f"{actual_nspf}/{actual_spf}",
                "ai_recommendation": recommendation,
                "ai_reason": reason,
                "is_correct": is_correct,
                "raw_data": raw_data
            })
            
            # 将 is_correct 写回数据库
            try:
                db.session.execute(text("UPDATE match_predictions SET is_correct = :is_correct, actual_result = :actual_result WHERE id = :id"), 
                    {"is_correct": is_correct, "actual_result": f"{actual_nspf}", "id": pred['id']})
            except Exception as e:
                print(f"  [WARN] 更新 is_correct 失败 for {match_num}: {e}")
            
            print(f"[{match_num}] {pred['home_team']} vs {pred['away_team']} | 比分: {actual_score} ({actual_nspf}/{actual_spf}) | AI推荐: {recommendation} | 命中: {is_correct}")

    # 提交数据库变更
    try:
        db.session.commit()
        print("\n[DB] is_correct 字段已同步到数据库")
    except Exception as e:
        print(f"\n[DB] 提交失败: {e}")

    print("\n========== 复盘统计 ==========")
    print(f"总计可对比场次: {total_compared}")
    if total_compared > 0:
        print(f"命中场次: {correct_count}")
        print(f"错误场次: {len(wrong_matches)}")
        print(f"整体胜率: {(correct_count/total_compared)*100:.2f}%")
        
    # 保存所有比对结果，供下一步生成完整文档
    import json
    with open(os.path.join(reports_dir, 'all_compared_matches.json'), 'w', encoding='utf-8') as f:
        json.dump(do_post_mortem.all_matches_report, f, ensure_ascii=False, indent=2)
        
    # 依然保存仅错误的供老逻辑使用
    with open(os.path.join(reports_dir, 'wrong_predictions.json'), 'w', encoding='utf-8') as f:
        json.dump(wrong_matches, f, ensure_ascii=False, indent=2)

    # 将错误案例自动存入独立目录，形成动态错题本 (V3 架构 - 第一阶段)
    error_db_dir = os.path.join(project_root, 'data', 'knowledge_base', 'errors')
    os.makedirs(error_db_dir, exist_ok=True)
    
    if wrong_matches:
        error_file = os.path.join(error_db_dir, f'errors_{yesterday}.json')
        try:
            with open(error_file, 'w', encoding='utf-8') as f:
                json.dump(wrong_matches, f, ensure_ascii=False, indent=2)
            print(f"[KB] 自动归档 {len(wrong_matches)} 个错题到知识库: {error_file}")
        except Exception as e:
            print(f"[KB] 保存错题本失败: {e}")

    # 4. 调用大模型对错误比赛进行原因分析（生成报告及CSV）
    from generate_detailed_report import generate_detailed_report
    generate_detailed_report(yesterday)

if __name__ == "__main__":
    import sys
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    do_post_mortem(target_date)
