import requests
from bs4 import BeautifulSoup
from loguru import logger
import re
import datetime

class SfcCrawler:
    def __init__(self):
        self.url = "https://trade.500.com/sfc/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def fetch_available_issues(self):
        """
        获取当前可用的期号列表
        """
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            if response.status_code != 200:
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            issues = []
            for tag in soup.find_all('a'):
                expect = tag.get('data-expect')
                if expect and '期' in tag.text:
                    issues.append(expect)
            
            # 去重并保持顺序（通常是最新的在前面）
            return list(dict.fromkeys(issues))
        except Exception as e:
            logger.error(f"获取胜负彩期号列表失败: {e}")
            return []

    def fetch_current_issue(self, issue_number=None):
        """
        抓取胜负彩十四场赛事列表（支持指定期号）
        :param issue_number: 指定期号，例如 '26069'。如果不传则默认抓取当前最新期
        """
        target_url = f"{self.url}?expect={issue_number}" if issue_number else self.url
        logger.info(f"开始抓取胜负彩赛事数据: {target_url}")
        try:
            response = requests.get(target_url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            
            if response.status_code != 200:
                logger.error(f"请求失败，状态码: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 获取期号
            issue_num = "未知期号"
            if issue_number:
                issue_num = str(issue_number)
            else:
                # 尝试从顶部选择期号的地方获取最新的或当前选中的期号
                a_tags = soup.find_all('a', attrs={'data-expect': True})
                if a_tags:
                    # 500彩票网的当前期号通常会有一个 'on' 的 class，或者排在第一个
                    for a in a_tags:
                        if 'on' in a.get('class', []):
                            issue_num = a.get('data-expect')
                            break
                    if issue_num == "未知期号":
                        issue_num = a_tags[0].get('data-expect')
                        
                # 兼容老版页面的备用方案
                if issue_num == "未知期号":
                    issue_div = soup.find('div', class_='bet-hd')
                    if issue_div:
                        b_tag = issue_div.find('b', class_='cfont_red')
                        if b_tag:
                            issue_num = b_tag.text.strip()
            
            logger.info(f"当前胜负彩期号: {issue_num}")
            
            matches = []
            table = soup.find('table', id='vsTable')
            if not table:
                logger.error("未找到比赛列表(vsTable)")
                return []
                
            rows = table.find_all('tr', class_='bet-tb-tr')
            current_year = datetime.datetime.now().year
            
            for row in rows:
                try:
                    tds = row.find_all('td')
                    if len(tds) < 8:
                        continue
                        
                    match_num = tds[0].text.strip()
                    league = tds[1].text.strip()
                    time_str = tds[2].text.strip() # "04-23 03:00"
                    
                    # 补充年份
                    match_time = f"{current_year}-{time_str}"
                    
                    teams_text = tds[3].text.strip()
                    parts = teams_text.split('VS')
                    if len(parts) != 2:
                        continue
                        
                    home_team = re.sub(r'\[.*?\]', '', parts[0]).strip()
                    away_team = re.sub(r'\[.*?\]', '', parts[1]).strip()
                    
                    # 查找 fid
                    fid = ""
                    for td in tds:
                        a_tag = td.find('a', href=re.compile(r'shuju-(\d+)\.shtml'))
                        if a_tag:
                            match = re.search(r'shuju-(\d+)\.shtml', a_tag['href'])
                            if match:
                                fid = match.group(1)
                                break
                    
                    matches.append({
                        "match_num": f"胜负彩_{match_num}",
                        "league": league,
                        "home_team": home_team,
                        "away_team": away_team,
                        "match_time": match_time,
                        "fixture_id": fid,
                        "issue_num": issue_num,
                        "odds": {}
                    })
                except Exception as e:
                    logger.warning(f"解析胜负彩单场出错: {e}")
                    continue
                    
            logger.info(f"成功解析 {len(matches)} 场胜负彩比赛")
            return matches
            
        except Exception as e:
            logger.error(f"抓取胜负彩数据发生异常: {e}")
            return []

if __name__ == "__main__":
    crawler = SfcCrawler()
    matches = crawler.fetch_current_issue()
    for m in matches[:3]:
        print(m)