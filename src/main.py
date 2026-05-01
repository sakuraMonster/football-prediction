import os
import sys
import json
from loguru import logger
from dotenv import load_dotenv

# 添加src到系统路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 初始化日志（终端 + 文件双输出）
from src.logging_config import setup_logging
setup_logging()

from src.crawler.jingcai_crawler import JingcaiCrawler
from src.crawler.jclq_crawler import JclqCrawler
from src.crawler.odds_crawler import OddsCrawler
from src.processor.data_fusion import DataFusion
from src.llm.predictor import LLMPredictor
from src.llm.bball_predictor import BBallPredictor
from src.crawler.nba_stats_crawler import NBAStatsCrawler
from src.db.database import Database

def main():
    logger.info("启动足球预测系统...")
    
    # ==========================
    # 足球部分
    # ==========================
    # 1. 抓取竞彩官方每日赛事
    logger.info("阶段1 & 2: 抓取竞彩赛程与赔率...")
    jingcai_crawler = JingcaiCrawler()
    matches = jingcai_crawler.fetch_today_matches()
    
    if not matches:
        logger.warning("今日无比赛或抓取失败。")
        return

    # 2. 抓取第三方数据源（基本面与外围盘口）& 3. 数据融合
    logger.info("阶段2 & 3: 抓取第三方基本面与盘赔数据并进行融合...")
    odds_crawler = OddsCrawler()
    data_fusion = DataFusion()
    leisu = None
    try:
        if os.getenv('LEISU_USERNAME'):
            from src.crawler.leisu_crawler import LeisuCrawler
            leisu = LeisuCrawler(headless=True)
    except Exception:
        pass
    merged_matches = data_fusion.merge_data(matches, odds_crawler, leisu_crawler=leisu)
    if leisu:
        try:
            leisu.close()
        except Exception:
            pass
    
    # 3.5 读取 Excel (foot_prediction.xlsx) 以获取进球盘口、差异和倾向
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        import pandas as pd
        excel_path = os.path.join(base_dir, "docs", "foot_prediction.xlsx")
        if os.path.exists(excel_path):
            xl = pd.ExcelFile(excel_path)
            # 获取最后一个 sheet，假设是最新的日期
            last_sheet = xl.sheet_names[-1]
            df_excel = pd.read_excel(xl, sheet_name=last_sheet)
            df_excel.columns = df_excel.columns.str.strip()
            df_excel['编码'] = df_excel['编码'].astype(str).str.strip()
            
            logger.info(f"成功读取 Excel 数据: {last_sheet}，准备将其融合进比赛数据...")
            
            for match in merged_matches:
                match_num = match.get('match_num')
                # 在 Excel 中查找匹配的编码
                row = df_excel[df_excel['编码'] == match_num]
                if not row.empty:
                    # 获取数据，处理可能的 NaN 或 float 格式
                    pan = row.iloc[0].get('进球盘口', '')
                    diff = row.iloc[0].get('预测差异百分比', '')
                    trend = row.iloc[0].get('倾向', '')
                    
                    match['goals_pan'] = str(pan).strip() if pd.notna(pan) else ""
                    match['goals_diff_percent'] = str(diff).strip() if pd.notna(diff) else ""
                    match['goals_trend'] = str(trend).strip() if pd.notna(trend) else ""
                    
    except Exception as e:
        logger.warning(f"读取 Excel 数据补充失败: {e}")
        
    # 将结果保存到本地 JSON 缓存 (使用绝对路径)
    cache_dir = os.path.join(base_dir, "data")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "today_matches.json")
    
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(merged_matches, f, ensure_ascii=False, indent=2)
    logger.info(f"比赛数据已保存至 {cache_file}")
    
    # 4. 调用大模型进行预测 (仅全场主模型)
    logger.info("阶段4: 调用大模型进行全场预测分析...")
    predictor = LLMPredictor()
    
    # 遍历预测所有比赛，并将结果存回字典
    total_count = len(merged_matches)
    
    for match in merged_matches:
        prediction_result, period = predictor.predict(match, total_matches_count=total_count)
        match["llm_prediction"] = prediction_result
        
        # 将带预测结果的数据覆盖保存
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(merged_matches, f, ensure_ascii=False, indent=2)
            
    logger.info("所有比赛主预测完成！")
    
    # 5. 存储预测结果
    logger.info("阶段5: 存储预测结果至数据库...")
    db = Database()
    for match in merged_matches:
        db.save_prediction(match)
    db.close()

    logger.info("今日足球预测任务全部完成！")

    # ==========================
    # 篮球部分
    # ==========================
    logger.info("开始处理竞彩篮球赛事...")
    jclq_crawler = JclqCrawler()
    bball_matches = jclq_crawler.fetch_today_matches()
    
    if bball_matches:
        bball_cache_file = os.path.join(cache_dir, "today_bball_matches.json")
        with open(bball_cache_file, "w", encoding="utf-8") as f:
            json.dump(bball_matches, f, ensure_ascii=False, indent=2)
        
        logger.info("阶段4: 获取最新基本面并调用大模型进行篮球比赛分析与预测...")
        bball_predictor = BBallPredictor()
        nba_stats_crawler = NBAStatsCrawler()
        
        total_bball_count = len(bball_matches)
        for match in bball_matches:
            # 拉取最新基本面
            if '美职篮' in match.get('league', ''):
                match['away_stats'] = nba_stats_crawler.get_team_stats(match.get('away_team'))
                match['home_stats'] = nba_stats_crawler.get_team_stats(match.get('home_team'))
                
            bball_pred_result = bball_predictor.predict(match, total_matches_count=total_bball_count)
            match["llm_prediction"] = bball_pred_result
            
            with open(bball_cache_file, "w", encoding="utf-8") as f:
                json.dump(bball_matches, f, ensure_ascii=False, indent=2)
                
        logger.info("所有篮球比赛预测完成！")
        
        logger.info("阶段5: 存储篮球预测结果至数据库...")
        db = Database()
        for match in bball_matches:
            db.save_bball_prediction(match)
        db.close()
        
        logger.info("今日篮球预测任务全部完成！")
    else:
        logger.warning("今日无篮球比赛或抓取失败。")

if __name__ == "__main__":
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(base_dir, "config", ".env"))
    main()
