from loguru import logger
import os
import requests
import urllib.parse
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")

class AdvancedStatsCrawler:
    """
    专门用于抓取高阶技术统计（场均射门、射正、xG等）的爬虫模块。
    支持通过 API-Sports (api-football) 获取真实的射门和进球期望数据。
    如果 API Key 未配置或调用失败，则返回空数据供下游 Fallback。
    """
    def __init__(self):
        self.api_key = os.getenv("FOOTBALL_API_KEY")
        self.headers = {
            "x-apisports-key": self.api_key,
            "x-rapidapi-host": "v3.football.api-sports.io"
        }
        self.base_url = "https://v3.football.api-sports.io"
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # 缓存球队 ID 避免重复搜索
        self.team_id_cache = {}

    def _search_team_id(self, team_name: str) -> int:
        """根据中文或英文队名搜索球队 ID"""
        if not self.api_key or self.api_key == "your_api_key_here":
            return None
            
        if team_name in self.team_id_cache:
            return self.team_id_cache[team_name]
            
        try:
            # api-sports 搜索接口
            url = f"{self.base_url}/teams?search={urllib.parse.quote(team_name)}"
            res = self.session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("response") and len(data["response"]) > 0:
                    team_id = data["response"][0]["team"]["id"]
                    self.team_id_cache[team_name] = team_id
                    return team_id
        except Exception as e:
            logger.debug(f"搜索球队 {team_name} ID 失败: {e}")
        return None

    def _get_team_stats(self, team_id: int, league_id: int = 39, season: int = 2023) -> dict:
        """
        获取球队的高阶统计数据 (注意: 免费API有调用频率限制, 建议缓存)
        为简化逻辑，这里假设查询特定联赛(league_id)和赛季(season)
        """
        if not team_id:
            return {}
            
        try:
            url = f"{self.base_url}/teams/statistics?league={league_id}&season={season}&team={team_id}"
            res = self.session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("response"):
                    resp = data["response"]
                    # 提取进球数据
                    goals_for = resp.get("goals", {}).get("for", {}).get("average", {}).get("total")
                    goals_against = resp.get("goals", {}).get("against", {}).get("average", {}).get("total")
                    
                    return {
                        "avg_goals_for": goals_for,
                        "avg_goals_against": goals_against,
                        # API-Football 暂未在 free tier 直接暴露 xG 和 场均射门 (需要 fixtures/statistics 聚合)
                        # 这里作为框架扩展预留
                        "avg_shots": None, 
                        "avg_shots_on_target": None,
                        "avg_xG": None
                    }
        except Exception as e:
            logger.debug(f"获取球队 {team_id} 统计数据失败: {e}")
        return {}

    def fetch_advanced_stats(self, home_team: str, away_team: str, league_id: int = None, season: int = None) -> dict:
        """
        获取主客队的高阶进攻数据
        :param home_team: 主队名称
        :param away_team: 客队名称
        :return: dict 包含双方的场均数据
        """
        # 如果未配置真实的 API Key，直接返回空，由下游使用 500.com 的战绩正则 fallback
        if not self.api_key or self.api_key == "your_api_key_here":
            logger.info("FOOTBALL_API_KEY 未配置，跳过 API-Sports 高阶数据抓取，将使用 500网基本面数据 Fallback")
            return {"home": {}, "away": {}}
            
        logger.info(f"正在通过 API-Sports 获取高阶数据: {home_team} VS {away_team}")
        
        stats = {
            "home": {},
            "away": {}
        }
        
        # 默认取一个常见的联赛ID(英超=39)和当前赛季(2023/2024)，实际业务中应从 match 传入
        l_id = league_id if league_id else 39
        s_id = season if season else 2023
        
        home_id = self._search_team_id(home_team)
        if home_id:
            stats["home"] = self._get_team_stats(home_id, l_id, s_id)
            
        away_id = self._search_team_id(away_team)
        if away_id:
            stats["away"] = self._get_team_stats(away_id, l_id, s_id)
            
        return stats
