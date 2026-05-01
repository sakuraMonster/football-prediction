import requests
from bs4 import BeautifulSoup
from loguru import logger
import datetime

class JingcaiCrawler:
    def __init__(self):
        self.url = "https://trade.500.com/jczq/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch_today_matches(self, target_date=None):
        """
        抓取竞彩赛事数据 (包含胜平负和半全场赔率)
        :param target_date: 可选，指定日期 (datetime.date 或 'YYYY-MM-DD' 字符串)，默认今天
        :return: list of dict, 包含比赛基本信息与赔率
        """
        logger.info(f"开始抓取竞彩赛事数据: {self.url}" + (f" (target_date={target_date})" if target_date else ""))
        try:
            # 1. 获取基础胜平负和让球胜平负
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            
            if response.status_code != 200:
                logger.error(f"请求失败，状态码: {response.status_code}")
                return []

            matches = self._parse_html(response.text, target_date=target_date)
            
            # 2. 获取半全场 (bqc) 赔率
            bqc_url = "https://trade.500.com/jczq/?playid=272"
            logger.info(f"开始抓取半全场赔率数据: {bqc_url}")
            bqc_res = requests.get(bqc_url, headers=self.headers, timeout=15)
            bqc_res.encoding = 'gb2312'
            if bqc_res.status_code == 200:
                bqc_matches = self._parse_bqc_html(bqc_res.text)
                # 合并半全场赔率
                for match in matches:
                    fid = match["fixture_id"]
                    if fid in bqc_matches:
                        match["odds"]["bqc"] = bqc_matches[fid]
            
            return matches
        except Exception as e:
            logger.error(f"抓取竞彩数据发生异常: {e}")
            return []

    def _parse_html(self, html_text, target_date=None):
        soup = BeautifulSoup(html_text, 'html.parser')
        match_rows = soup.find_all('tr', class_='bet-tb-tr')
        
        # 确定目标日期的周几前缀，例如 "周六"
        if target_date:
            if isinstance(target_date, str):
                target_dt = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            else:
                target_dt = datetime.datetime.combine(target_date, datetime.datetime.min.time()) if hasattr(target_date, 'strftime') else target_date
            target_weekday = target_dt.strftime("%A")
        else:
            target_weekday = datetime.datetime.now().strftime("%A")
        weekday_map = {
            "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
            "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"
        }
        current_day_prefix = weekday_map.get(target_weekday, "")
        
        matches = []
        for row in match_rows:
            try:
                # 检查是否被隐藏或者已停售
                style = row.get('style', '')
                if 'display:none' in style.replace(' ', ''):
                    continue

                match_num = row.get('data-matchnum', '')
                if not match_num:
                    continue
                    
                # 只保留编号前缀和今天一致的比赛
                if current_day_prefix and not match_num.startswith(current_day_prefix):
                    continue

                fixture_id = row.get('data-fixtureid', '')
                league = row.get('data-simpleleague', '')
                home_team = row.get('data-homesxname', '')
                away_team = row.get('data-awaysxname', '')
                match_time = row.get('data-matchtime', '')
                match_date = row.get('data-matchdate', '')
                
                # 提取不让球胜平负赔率 (胜, 平, 负)
                nspf_btns = row.find_all('p', {'data-type': 'nspf'})
                nspf_sp = [btn.get('data-sp', '-') for btn in nspf_btns]
                
                # 提取让球胜平负赔率
                spf_btns = row.find_all('p', {'data-type': 'spf'})
                spf_sp = [btn.get('data-sp', '-') for btn in spf_btns]
                
                rangqiu = row.get('data-rangqiu', '0')

                match_info = {
                    "fixture_id": fixture_id,
                    "match_num": match_num,
                    "league": league,
                    "home_team": home_team,
                    "away_team": away_team,
                    "match_time": f"{match_date} {match_time}",
                    "odds": {
                        "nspf": nspf_sp if len(nspf_sp) == 3 else ["-", "-", "-"],  # 不让球 胜平负
                        "spf": spf_sp if len(spf_sp) == 3 else ["-", "-", "-"],     # 让球 胜平负
                        "rangqiu": rangqiu
                    }
                }
                matches.append(match_info)
            except Exception as e:
                logger.warning(f"解析某场比赛出错: {e}")
                continue
                
        logger.info(f"成功解析出 {len(matches)} 场竞彩比赛。")
        return matches

    def _parse_bqc_html(self, html_text):
        """解析半全场赔率 (bqc)"""
        soup = BeautifulSoup(html_text, 'html.parser')
        match_rows = soup.find_all('tr', class_='bet-tb-tr')
        
        bqc_dict = {}
        for row in match_rows:
            try:
                style = row.get('style', '')
                if 'display:none' in style.replace(' ', ''):
                    continue

                fixture_id = row.get('data-fixtureid', '')
                if not fixture_id:
                    continue
                
                # 提取半全场赔率 (bqc)
                # 格式：3-3(胜胜), 3-1(胜平), 3-0(胜负), 1-3(平胜), 1-1(平平), 1-0(平负), 0-3(负胜), 0-1(负平), 0-0(负负)
                bqc_btns = row.find_all('p', {'data-type': 'bqc'})
                bqc_sp = {btn.get('data-value', ''): btn.get('data-sp', '-') for btn in bqc_btns if btn.get('data-value')}
                
                if bqc_sp:
                    bqc_dict[fixture_id] = bqc_sp
                    
            except Exception as e:
                continue
        return bqc_dict

    def fetch_match_results(self, target_date):
        """
        抓取指定日期的比赛赛果
        target_date: 格式 'YYYY-MM-DD'
        :return: dict, {match_num: score}
        """
        # 使用和 fetch_today_matches 一样的竞彩标准接口
        url = f"https://trade.500.com/jczq/?date={target_date}"
        logger.info(f"开始抓取 {target_date} 赛果: {url}")
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            
            if response.status_code != 200:
                logger.error(f"请求失败，状态码: {response.status_code}")
                return {}

            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.find_all('tr', class_='bet-tb-tr')
            results = {}
            
            # 推理前缀，只保留目标日的比赛
            target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            weekday_map = {
                "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
                "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"
            }
            target_day_prefix = weekday_map.get(target_dt.strftime("%A"), "")
            
            for row in rows:
                match_num = row.get('data-matchnum', '')
                if not match_num:
                    continue
                    
                if target_day_prefix and not match_num.startswith(target_day_prefix):
                    continue
                    
                score_tag = row.find('a', class_='score')
                if score_tag:
                    score_text = score_tag.text.strip()
                    if ":" in score_text:
                        # 从抓取到的数据中提取比赛时间(如果没有提供就只有比分)
                        match_time = row.get('data-matchtime', '')
                        match_date = row.get('data-matchdate', '')
                        full_time = f"{match_date} {match_time}" if match_date and match_time else None
                        home_team = row.get('data-homesxname', '')
                        away_team = row.get('data-awaysxname', '')
                        
                        # 记录赛果以及时间以便后续精准匹配
                        results[match_num] = {
                            "score": score_text,
                            "match_time": full_time,
                            "home_team": home_team,
                            "away_team": away_team
                        }
            
            logger.info(f"成功获取到 {len(results)} 场比赛的赛果。")
            
            # 额外抓取半全场赛果 (用于支持半全场模式的回测)
            bqc_url = f"https://trade.500.com/jczq/?date={target_date}&playid=272"
            try:
                bqc_res = requests.get(bqc_url, headers=self.headers, timeout=15)
                bqc_res.encoding = 'gb2312'
                if bqc_res.status_code == 200:
                    bqc_soup = BeautifulSoup(bqc_res.text, 'html.parser')
                    bqc_rows = bqc_soup.find_all('tr', class_='bet-tb-tr')
                    for row in bqc_rows:
                        match_num = row.get('data-matchnum', '')
                        if not match_num or match_num not in results:
                            continue
                        
                        # 找出中了的那个半全场选项 (带有 betbtn-ok 类)
                        ok_btn = row.find('p', class_='betbtn-ok')
                        if ok_btn and ok_btn.get('data-type') == 'bqc':
                            results[match_num]['bqc_result'] = ok_btn.get('data-value') # e.g. "1-3"
            except Exception as e:
                logger.warning(f"获取半全场赛果失败: {e}")
                
            return results
        except Exception as e:
            logger.error(f"抓取赛果发生异常: {e}")
            return {}

    def fetch_history_matches(self, target_date):
        """
        从500彩票网历史页面拉取指定日期的已完赛比赛数据（含赔率和赛果）。
        用于复盘场景，只拉取数据不预测。
        URL: https://trade.500.com/jczq/?playid=269&g=2&date=YYYY-MM-DD
        :param target_date: str 'YYYY-MM-DD' 或 datetime.date
        :return: list of dict，每场比赛含基本信息、赔率、比分
        """
        if isinstance(target_date, datetime.date):
            target_date = target_date.strftime("%Y-%m-%d")
        url = f"https://trade.500.com/jczq/?playid=269&g=2&date={target_date}"
        logger.info(f"开始抓取历史比赛数据: {url}")
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            if response.status_code != 200:
                logger.error(f"请求失败，状态码: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.find_all('tr', class_='bet-tb-tr')
            
            # 确定目标日期的周几前缀
            target_dt = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            weekday_map = {
                "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
                "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"
            }
            day_prefix = weekday_map.get(target_dt.strftime("%A"), "")
            
            matches = []
            for row in rows:
                try:
                    match_num = row.get('data-matchnum', '')
                    if not match_num:
                        continue
                    if day_prefix and not match_num.startswith(day_prefix):
                        continue
                    
                    fixture_id = row.get('data-fixtureid', '')
                    league = row.get('data-simpleleague', '')
                    home_team = row.get('data-homesxname', '')
                    away_team = row.get('data-awaysxname', '')
                    match_time = row.get('data-matchtime', '')
                    match_date = row.get('data-matchdate', '')
                    rangqiu = row.get('data-rangqiu', '0')
                    
                    # 提取比分
                    score_elem = row.find('a', class_='score')
                    actual_score = score_elem.text.strip() if score_elem else ''
                    
                    # 提取不让球赔率
                    nspf_btns = row.find_all('p', {'data-type': 'nspf'})
                    nspf_sp = [btn.get('data-sp', '-') for btn in nspf_btns if 'betbtn-ok' not in (btn.get('class') or [])]
                    # 如果以上方式过滤不干净，取前3个
                    if len(nspf_btns) >= 3:
                        nspf_sp = [nspf_btns[i].get('data-sp', '-') for i in range(3)]
                    else:
                        nspf_sp = [btn.get('data-sp', '-') for btn in nspf_btns]
                    
                    # 提取让球赔率
                    spf_btns = row.find_all('p', {'data-type': 'spf'})
                    if len(spf_btns) >= 3:
                        spf_sp = [spf_btns[i].get('data-sp', '-') for i in range(3)]
                    else:
                        spf_sp = [btn.get('data-sp', '-') for btn in spf_btns]
                    
                    match_info = {
                        "fixture_id": fixture_id,
                        "match_num": match_num,
                        "league": league,
                        "home_team": home_team,
                        "away_team": away_team,
                        "match_time": f"{match_date} {match_time}",
                        "actual_score": actual_score,
                        "odds": {
                            "nspf": nspf_sp if len(nspf_sp) == 3 else ["-", "-", "-"],
                            "spf": spf_sp if len(spf_sp) == 3 else ["-", "-", "-"],
                            "rangqiu": rangqiu
                        }
                    }
                    matches.append(match_info)
                except Exception as e:
                    logger.warning(f"解析历史比赛出错: {e}")
                    continue
            
            logger.info(f"历史数据拉取完成: {target_date}，共 {len(matches)} 场")
            return matches
        except Exception as e:
            logger.error(f"抓取历史比赛数据异常: {e}")
            return []

if __name__ == "__main__":
    crawler = JingcaiCrawler()
    matches = crawler.fetch_today_matches()
    for m in matches[:3]:
        print(m)
