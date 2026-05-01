import requests
from bs4 import BeautifulSoup
from loguru import logger
import re

from src.crawler.advanced_stats_crawler import AdvancedStatsCrawler

class OddsCrawler:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        self.advanced_stats_crawler = AdvancedStatsCrawler()

    def fetch_match_details(self, fixture_id, home_team=None, away_team=None):
        """
        抓取单场比赛的基本面与盘赔数据
        """
        data = {
            "asian_odds": {},
            "europe_odds": {},
            "recent_form": {},
            "h2h": [],
            "advanced_stats": {}
        }
        
        # 抓取高阶进攻数据 (如果有球队名称)
        if home_team and away_team:
            data["advanced_stats"] = self.advanced_stats_crawler.fetch_advanced_stats(home_team, away_team)
            
        try:
            # 1. 获取亚指
            yazhi_url = f"https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml"
            res = requests.get(yazhi_url, headers=self.headers, timeout=10)
            res.encoding = 'gb2312'
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.find('table', id='datatb')
            if table:
                for row in table.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) < 12: continue
                    
                    company = cells[1].text.strip() if not cells[1].find('span', class_='quancheng') else cells[1].find('span', class_='quancheng').text.strip()
                    
                    # 500网未登录状态下会隐藏公司名，如 "*门" (澳门), "**t3*5" (bet365)
                    is_macau = "澳门" in company or "*门" in company
                    is_bet365 = "Bet365" in company or "bet365" in company.lower() or "t3*5" in company
                    
                    if is_macau or is_bet365:
                        try:
                            # 根据最新分析，分离的即时盘在 index 3, 4, 5
                            live_up = cells[3].text.strip()
                            live_pan = cells[4].text.strip()
                            live_down = cells[5].text.strip()
                            
                            # 分离的初盘在 index 9, 10, 11
                            start_up = cells[9].text.strip()
                            start_pan = cells[10].text.strip()
                            start_down = cells[11].text.strip()
                            
                            comp_key = "macau" if is_macau else "bet365"
                            data["asian_odds"][comp_key] = {
                                "start": f"{start_up} | {start_pan} | {start_down}",
                                "live": f"{live_up} | {live_pan} | {live_down}"
                            }
                        except Exception as e:
                            logger.error(f"提取亚指错误 {company}: {e}")

            # 2. 获取基本面 (近期战绩, 交锋, 积分排名, 澳门心水)
            shuju_url = f"https://odds.500.com/fenxi/shuju-{fixture_id}.shtml"
            res2 = requests.get(shuju_url, headers=self.headers, timeout=10)
            res2.encoding = 'gb2312'
            soup2 = BeautifulSoup(res2.text, 'html.parser')
            
            # 2.1 & 2.2 积分排名和近期战绩
            m_contents = soup2.find_all('div', class_='M_content')
            if len(m_contents) > 0:
                tables = m_contents[0].find_all('table')
                if len(tables) >= 2:
                    try:
                        home_rows = tables[0].find_all('tr')
                        away_rows = tables[1].find_all('tr')
                        
                        if len(home_rows) > 1 and len(away_rows) > 1:
                            home_cols = [c.text.strip() for c in home_rows[1].find_all('td')]
                            away_cols = [c.text.strip() for c in away_rows[1].find_all('td')]
                            
                            if len(home_cols) >= 10 and len(away_cols) >= 10:
                                # 确保不是空数据（例如杯赛的积分榜往往是空的）
                                if home_cols[1] and home_cols[1].isdigit():
                                    # 索引 8 是积分，9 是排名
                                    data["recent_form"]["standings"] = f"主队积分{home_cols[8]}排名{home_cols[9]}, 客队积分{away_cols[8]}排名{away_cols[9]}"
                                    data["recent_form"]["home"] = f"{home_cols[1]}战{home_cols[2]}胜{home_cols[3]}平{home_cols[4]}负 进{home_cols[5]}失{home_cols[6]}"
                                    data["recent_form"]["away"] = f"{away_cols[1]}战{away_cols[2]}胜{away_cols[3]}平{away_cols[4]}负 进{away_cols[5]}失{away_cols[6]}"
                    except Exception as e:
                        logger.error(f"提取积分排名与战绩错误: {e}")

            # 2.3 交战历史
            h2h_text = ''
            for title in soup2.find_all('div', class_='M_title'):
                if '交战历史' in title.text:
                    h2h_text = title.text.replace('交战历史', '').replace('\n', ' ').replace('\r', '').strip()
                    break
            if h2h_text:
                data["h2h_summary"] = h2h_text
            else:
                # 兼容旧版提取方式
                team_jiaofeng = soup2.find('div', class_='team_a')
                if team_jiaofeng:
                    bottom_info = team_jiaofeng.find('div', class_='bottom_info')
                    if bottom_info:
                        data["h2h_summary"] = bottom_info.text.strip()

            # 2.4 澳门心水推荐 (通常在最后一个 M_content)
            if len(m_contents) > 0:
                last_content = m_contents[-1]
                macau_text = last_content.text.strip().replace('\n', ' | ')
                macau_text = re.sub(r'\|\s*\|+', '|', macau_text)
                if '推介' in macau_text or '近况走势' in macau_text:
                    data["recent_form"]["macau_recommendation"] = macau_text

            # 2.5 伤停与阵容信息
            injuries_text = []
            for title in soup2.find_all('div', class_='M_title'):
                if '预计阵容' in title.text or '阵容' in title.text:
                    content = title.find_next_sibling('div', class_='M_content')
                    if content:
                        tables = content.find_all('table')
                        for i, tb in enumerate(tables):
                            headers = [th.text.strip() for th in tb.find_all('th')]
                            if '- 伤病 -' in headers:
                                idx = headers.index('- 伤病 -')
                                idx_susp = headers.index('- 停赛 -') if '- 停赛 -' in headers else -1
                                injuries = []
                                suspensions = []
                                for r in tb.find_all('tr'):
                                    cols = [c.text.strip() for c in r.find_all('td')]
                                    if len(cols) > idx and cols[idx]:
                                        injuries.append(cols[idx])
                                    if idx_susp != -1 and len(cols) > idx_susp and cols[idx_susp]:
                                        suspensions.append(cols[idx_susp])
                                
                                prefix = "主队" if i == 0 else "客队"
                                if injuries:
                                    injuries_text.append(f"{prefix}伤病: {', '.join(injuries)}")
                                if suspensions:
                                    injuries_text.append(f"{prefix}停赛: {', '.join(suspensions)}")
            if injuries_text:
                data["recent_form"]["injuries"] = " | ".join(injuries_text)
            else:
                data["recent_form"]["injuries"] = "暂无详细伤停数据"
                    
        except Exception as e:
            logger.error(f"抓取 fixture_id={fixture_id} 详情失败: {e}")
            
        return data

if __name__ == "__main__":
    crawler = OddsCrawler()
    # 填入之前测试拿到的 fixture_id: 1205427
    print(crawler.fetch_match_details("1205427"))
