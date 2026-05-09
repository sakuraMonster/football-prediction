import os
from loguru import logger


def build_leisu_crawler(headless=True):
    """按环境开关创建雷速爬虫实例，关闭或初始化失败时返回 None。"""
    enable_leisu = os.getenv("ENABLE_LEISU", "1").lower() not in ("0", "false", "no", "off")
    if not enable_leisu:
        return None

    try:
        from src.crawler.leisu_crawler import LeisuCrawler
        return LeisuCrawler(headless=headless)
    except Exception as e:
        logger.warning(f"雷速爬虫初始化失败: {e}")
        return None


def inject_leisu_data(match, leisu_crawler):
    """为单场比赛注入雷速体育的伤停/交锋/进球分布等数据（可直接复用已打开的爬虫实例）"""
    if not leisu_crawler:
        return
    try:
        leisu_data = leisu_crawler.fetch_match_data(
            match.get('home_team'),
            match.get('away_team'),
            match.get('match_time')
        )
        if leisu_data:
            _apply_leisu_data(match, leisu_data)
            return True
    except Exception as e:
        import traceback
        logger.warning(f"雷速数据注入失败 {match.get('match_num')}: {e}")
        logger.warning(traceback.format_exc())
    return False


def _apply_leisu_data(match, leisu_data):
    match['leisu_data'] = leisu_data
    if leisu_data.get('injuries'):
        match['injuries_detailed'] = {'injuries_text': leisu_data['injuries']}
    if leisu_data.get('goal_distribution'):
        match['goal_distribution'] = leisu_data['goal_distribution']
    if leisu_data.get('htft'):
        match['htft_data'] = leisu_data['htft']
    if leisu_data.get('standings'):
        match['standings_info'] = leisu_data['standings']
    if leisu_data.get('h2h_scores'):
        match['h2h_leisu'] = leisu_data['h2h_scores']
    if leisu_data.get('recent_scores'):
        match['recent_leisu'] = leisu_data['recent_scores']
    if leisu_data.get('match_intelligence'):
        match['leisu_intelligence'] = leisu_data['match_intelligence']


class DataFusion:
    def __init__(self):
        pass

    def merge_data(self, jingcai_matches, odds_crawler, leisu_crawler=None):
        """
        融合竞彩基础数据和第三方盘赔/基本面数据
        :param leisu_crawler: 可选的 LeisuCrawler 实例，用于从雷速体育获取伤停/交锋等数据
        """
        logger.info("开始融合数据...")
        merged_matches = []
        
        for match in jingcai_matches:
            fixture_id = match.get("fixture_id")
            if not fixture_id:
                logger.warning(f"比赛 {match['match_num']} 没有 fixture_id，跳过抓取详细数据")
                merged_matches.append(match)
                continue
                
            logger.info(f"正在抓取 {match['match_num']} ({match['home_team']} VS {match['away_team']}) 的详细盘赔数据...")
            details = odds_crawler.fetch_match_details(
                fixture_id, 
                home_team=match.get('home_team'), 
                away_team=match.get('away_team')
            )
            
            # 将详细数据合并到比赛信息中
            match["asian_odds"] = details.get("asian_odds", {})
            match["europe_odds"] = details.get("europe_odds", [])
            match["recent_form"] = details.get("recent_form", {})
            match["h2h_summary"] = details.get("h2h_summary", "")
            match["advanced_stats"] = details.get("advanced_stats", {})

            # --- 雷速体育数据增强 ---
            if leisu_crawler:
                try:
                    leisu_data = leisu_crawler.fetch_match_data(
                        match.get('home_team'),
                        match.get('away_team'),
                        match.get('match_time')
                    )
                    if leisu_data:
                        _apply_leisu_data(match, leisu_data)
                        logger.info(f"  雷速数据已注入: {match['match_num']}")
                except Exception as e:
                    logger.warning(f"  雷速抓取失败 {match['match_num']}: {e}")
            
            merged_matches.append(match)
            
        logger.info("数据融合完成！")
        return merged_matches
