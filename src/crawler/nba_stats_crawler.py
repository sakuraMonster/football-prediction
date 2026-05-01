import requests
import json
from loguru import logger
import re

class NBAStatsCrawler:
    def __init__(self):
        self.teams_url = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams'
        self.roster_url_tpl = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster'
        self.team_id_map = {}
        
    def _init_team_map(self):
        """初始化 NBA 球队名称与 ESPN ID 的映射"""
        if self.team_id_map:
            return
            
        try:
            resp = requests.get(self.teams_url, timeout=10)
            data = resp.json()
            teams_data = data.get('sports', [])[0].get('leagues', [])[0].get('teams', [])
            
            for t in teams_data:
                team_info = t.get('team', {})
                name = team_info.get('displayName')
                team_id = team_info.get('id')
                # 取最后一个单词作为简称（如 Lakers, Celtics）以提高匹配率
                short_name = name.split()[-1]
                self.team_id_map[short_name] = team_id
                self.team_id_map[name] = team_id
                
            # 手动添加一些常见的中文映射
            self.team_id_map['老鹰'] = self.team_id_map.get('Hawks')
            self.team_id_map['凯尔特人'] = self.team_id_map.get('Celtics')
            self.team_id_map['篮网'] = self.team_id_map.get('Nets')
            self.team_id_map['黄蜂'] = self.team_id_map.get('Hornets')
            self.team_id_map['公牛'] = self.team_id_map.get('Bulls')
            self.team_id_map['骑士'] = self.team_id_map.get('Cavaliers')
            self.team_id_map['独行侠'] = self.team_id_map.get('Mavericks')
            self.team_id_map['掘金'] = self.team_id_map.get('Mavericks') # ESPN API 中，13是Lakers, Mavericks是11
            self.team_id_map['掘金'] = self.team_id_map.get('Nuggets')
            self.team_id_map['活塞'] = self.team_id_map.get('Cavaliers')
            self.team_id_map['活塞'] = self.team_id_map.get('Pistons')
            self.team_id_map['勇士'] = self.team_id_map.get('Warriors')
            self.team_id_map['火箭'] = self.team_id_map.get('Warriors')
            self.team_id_map['火箭'] = self.team_id_map.get('Rockets')
            self.team_id_map['步行者'] = self.team_id_map.get('Pacers')
            self.team_id_map['快船'] = self.team_id_map.get('Lakers')
            self.team_id_map['快船'] = self.team_id_map.get('Clippers')
            self.team_id_map['湖人'] = self.team_id_map.get('Lakers')
            self.team_id_map['灰熊'] = self.team_id_map.get('Grizzlies')
            self.team_id_map['热火'] = self.team_id_map.get('Heat')
            self.team_id_map['雄鹿'] = self.team_id_map.get('Bucks')
            self.team_id_map['森林狼'] = self.team_id_map.get('Timberwolves')
            self.team_id_map['鹈鹕'] = self.team_id_map.get('Pelicans')
            self.team_id_map['尼克斯'] = self.team_id_map.get('Knicks')
            self.team_id_map['雷霆'] = self.team_id_map.get('Thunder')
            self.team_id_map['魔术'] = self.team_id_map.get('Magic')
            self.team_id_map['76人'] = self.team_id_map.get('76ers')
            self.team_id_map['太阳'] = self.team_id_map.get('Suns')
            self.team_id_map['开拓者'] = self.team_id_map.get('Pelicans')
            self.team_id_map['开拓者'] = self.team_id_map.get('Trail Blazers')
            self.team_id_map['国王'] = self.team_id_map.get('Kings')
            self.team_id_map['马刺'] = self.team_id_map.get('Spurs')
            self.team_id_map['猛龙'] = self.team_id_map.get('Raptors')
            self.team_id_map['爵士'] = self.team_id_map.get('Jazz')
            self.team_id_map['奇才'] = self.team_id_map.get('Wizards')
            
        except Exception as e:
            logger.error(f"初始化 NBA 球队映射失败: {e}")

    def get_team_stats(self, team_name):
        """获取球队的伤停情况和近期战绩"""
        self._init_team_map()
        
        team_id = None
        for key, tid in self.team_id_map.items():
            if key in team_name or team_name in key:
                team_id = tid
                break
                
        if not team_id:
            return {"injuries": f"未能匹配到球队 '{team_name}' 的伤停数据", "record": "未知"}
            
        result = {"injuries": "", "record": "未知"}
        
        # 1. 获取伤停
        try:
            roster_url = self.roster_url_tpl.format(team_id)
            resp = requests.get(roster_url, timeout=10).json()
            
            injuries = []
            for athlete in resp.get('athletes', []):
                for p in athlete.get('items', []):
                    player_injuries = p.get('injuries', [])
                    if player_injuries:
                        status = player_injuries[0].get('status', 'Unknown')
                        # 翻译常见的状态
                        status_zh = status
                        if status.lower() == 'out': status_zh = '缺阵'
                        elif status.lower() == 'day-to-day': status_zh = '出战成疑'
                        elif status.lower() == 'suspension': status_zh = '禁赛'
                        
                        name = p.get('fullName', '')
                        injuries.append(f"{name}({status_zh})")
            
            if not injuries:
                result["injuries"] = "全员健康，无主力伤停"
            else:
                result["injuries"] = "、".join(injuries)
        except Exception as e:
            logger.error(f"获取 {team_name} 伤停失败: {e}")
            result["injuries"] = "获取伤停数据失败"
            
        # 2. 获取战绩 (胜-负)
        try:
            team_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}"
            resp = requests.get(team_url, timeout=10).json()
            team_data = resp.get('team', {})
            records = team_data.get('record', {}).get('items', [])
            if records:
                result["record"] = records[0].get('summary', '未知')
        except Exception as e:
            logger.error(f"获取 {team_name} 战绩失败: {e}")
            
        return result

if __name__ == "__main__":
    crawler = NBAStatsCrawler()
    stats1 = crawler.get_team_stats("湖人")
    print("湖人:", stats1)
    stats2 = crawler.get_team_stats("独行侠")
    print("独行侠:", stats2)
