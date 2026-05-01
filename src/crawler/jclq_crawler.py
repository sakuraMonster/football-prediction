import requests
from bs4 import BeautifulSoup
from loguru import logger
import datetime

class JclqCrawler:
    def __init__(self):
        # 使用混合过关的URL，确保能拉取到所有包含混合玩法的赛事（例如303和305）
        self.url = "https://trade.500.com/jclq/?playid=313&g=2"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch_today_matches(self):
        """
        抓取今天可购买的竞彩篮球赛事数据
        :return: list of dict, 包含比赛基本信息与赔率
        """
        logger.info(f"开始抓取竞彩篮球赛事数据: {self.url}")
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.encoding = 'gb2312'
            
            if response.status_code != 200:
                logger.error(f"请求失败，状态码: {response.status_code}")
                return []

            return self._parse_html(response.text)
        except Exception as e:
            logger.error(f"抓取竞彩篮球数据发生异常: {e}")
            return []

    def _parse_html(self, html_text):
        soup = BeautifulSoup(html_text, 'html.parser')
        match_rows = soup.find_all('tr', class_='bet-tb-tr')
        
        # 确定今天是周几，例如 "周六"
        today_weekday = datetime.datetime.now().strftime("%A")
        weekday_map = {
            "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
            "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"
        }
        current_day_prefix = weekday_map.get(today_weekday, "")
        
        matches = []
        for row in match_rows:
            try:
                # 检查是否被隐藏或者已停售 (注释掉此逻辑，以确保能抓取到即将开售的比赛)
                # style = row.get('style', '')
                # if 'display:none' in style.replace(' ', ''):
                #     continue

                match_num = row.get('data-matchnum', '')
                if not match_num:
                    continue
                    
                # 只保留编号前缀和今天一致的比赛
                if current_day_prefix and not match_num.startswith(current_day_prefix):
                    continue

                fixture_id = row.get('data-fixtureid', '') or row.get('data-id', '')
                league = row.get('data-simpleleague', '')
                
                # 注意：500彩票网的篮球数据中，主客队顺序与足球不同
                # 页面显示为：客队VS主队 (如：凯尔特人VS老鹰)
                # data-homesxname 实际上存放的是主队（老鹰），data-awaysxname 存放的是客队（凯尔特人）
                # 为了保持统一，这里修复取值逻辑
                home_team = row.get('data-homesxname', '')
                away_team = row.get('data-awaysxname', '')
                
                # 有些场次的赔率和让分数据由于比赛变动可能会变成“-”，需要动态解析
                match_time = row.get('data-matchtime', '')
                match_date = row.get('data-matchdate', '')
                
                # 重新解析盘口，优先从赔率按钮所在的列获取最新数据
                rangfen = row.get('data-rangfen', '')
                yszf = row.get('data-yszf', '')
                
                # 解析真实的盘口值（防止 data- 属性未更新）
                tds = row.find_all('td')
                if len(tds) > 6:
                    # 寻找让分值：通常在含有 rfsf 按钮的 td 内部
                    for btn in row.find_all('p', {'data-type': 'rfsf'}):
                        if btn.find_parent('td'):
                            span_rf = btn.find_parent('td').find('span', class_='eng')
                            if span_rf:
                                rangfen = span_rf.text.strip()
                                break
                    
                    # 寻找大小分值：通常在含有 dxf 按钮的 td 内部
                    for btn in row.find_all('p', {'data-type': 'dxf'}):
                        if btn.find_parent('td'):
                            span_dxf = btn.find_parent('td').find('span', class_='eng')
                            if span_dxf:
                                yszf = span_dxf.text.strip()
                                break
                
                # 修复正负号逻辑
                # 在500网的篮球数据中，页面上展示的“让分”和“主客队”的关系比较特殊。
                # 页面显示的对阵是：客队 VS 主队。
                # 而让分值（如 -2.5）是针对主队而言的。也就是说如果页面显示“-2.5”，代表主队让客队2.5分。
                # 我们的 `data-homesxname` 取到的是真正的主队（老鹰），`data-awaysxname` 取到的是真正的客队（凯尔特人）。
                # 为了防止大模型理解混乱，这里我们不做数值的正负翻转，只需要在传递给大模型时说明“该让分值是针对主队的”即可。
                
                # 提取胜负(SF)赔率 [客胜, 主胜] - 注意篮球一般是客队在前
                sf_btns = row.find_all('p', {'data-type': 'sf'})
                sf_sp = [btn.get('data-sp', '-') for btn in sf_btns]
                
                # 提取让分胜负(RFSF)赔率 [让分客胜, 让分主胜]
                rfsf_btns = row.find_all('p', {'data-type': 'rfsf'})
                rfsf_sp = [btn.get('data-sp', '-') for btn in rfsf_btns]
                
                # 提取大小分(DXF)赔率 [大分, 小分]
                dxf_btns = row.find_all('p', {'data-type': 'dxf'})
                dxf_sp = [btn.get('data-sp', '-') for btn in dxf_btns]

                match_info = {
                    "fixture_id": fixture_id,
                    "match_num": match_num,
                    "league": league,
                    "home_team": home_team,
                    "away_team": away_team,
                    "match_time": f"{match_date} {match_time}",
                    "odds": {
                        "sf": sf_sp if len(sf_sp) >= 2 else ["-", "-"],
                        "rfsf": rfsf_sp if len(rfsf_sp) >= 2 else ["-", "-"],
                        "dxf": dxf_sp if len(dxf_sp) >= 2 else ["-", "-"],
                        "rangfen": rangfen,
                        "yszf": yszf
                    }
                }
                matches.append(match_info)
            except Exception as e:
                logger.warning(f"解析某场篮球比赛出错: {e}")
                continue
                
        logger.info(f"成功解析出 {len(matches)} 场竞彩篮球比赛。")
        return matches

    def fetch_match_results(self, target_date=None):
        """
        抓取指定日期（如 '2026-04-07'）的竞彩篮球历史赛果
        """
        if not target_date:
            from datetime import datetime, timedelta
            target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
        logger.info(f"开始抓取 {target_date} 的竞彩篮球赛果数据...")
        
        # 篮球混合过关历史赛果 URL
        # 注：使用 playid=313（混合过关）
        url = f"https://trade.500.com/jclq/?date={target_date}&playid=313&g=2"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'gbk' 
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"抓取篮球赛果数据失败: {e}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 修复选择器：500网的比赛行class是 'bet-tb-tr'
        match_rows = soup.find_all('tr', class_='bet-tb-tr')
        
        if not match_rows:
            logger.warning(f"未找到 {target_date} 的篮球比赛数据。")
            return []
            
        results = []
        for row in match_rows:
            try:
                # 获取比赛基础信息
                match_num = row.find('td', class_='td-no').text.strip()
                home_team = row.get('data-homesxname')
                away_team = row.get('data-awaysxname')
                
                # 提取实际比分
                # 在500网篮球混合过关历史页面，比分通常在一个 class='score' 的 a 标签中
                score_a = row.find('a', class_='score')
                if not score_a or not score_a.text.strip() or ':' not in score_a.text:
                    continue
                    
                score_text = score_a.text.strip()
                away_score_str, home_score_str = score_text.split(':')
                try:
                    away_score = int(away_score_str)
                    home_score = int(home_score_str)
                except ValueError:
                    continue
                
                # 获取让分和预设总分
                rangfen = "0"
                for btn in row.find_all('p', {'data-type': 'rfsf'}):
                    if btn.find_parent('td'):
                        span_rf = btn.find_parent('td').find('span', class_='eng')
                        if span_rf:
                            rangfen = span_rf.text.strip()
                            break
                            
                yszf = "0"
                for btn in row.find_all('p', {'data-type': 'dxf'}):
                    if btn.find_parent('td'):
                        span_dxf = btn.find_parent('td').find('span', class_='eng')
                        if span_dxf:
                            yszf = span_dxf.text.strip()
                            break
                
                # 计算胜负结果
                # 主胜/主负
                if home_score > away_score:
                    sf_result = "主胜"
                else:
                    sf_result = "客胜"
                    
                # 计算让分胜负结果
                try:
                    rf_val = float(rangfen)
                    if (home_score + rf_val) > away_score:
                        rfsf_result = "让分主胜"
                    else:
                        rfsf_result = "让分客胜"
                except:
                    rfsf_result = "未知"
                    
                # 计算大小分结果
                try:
                    total_score = home_score + away_score
                    yz_val = float(yszf)
                    if total_score > yz_val:
                        dxf_result = "大分"
                    else:
                        dxf_result = "小分"
                except:
                    dxf_result = "未知"
                
                results.append({
                    "match_num": match_num,
                    "home_team": home_team,
                    "away_team": away_team,
                    "score": f"{away_score}:{home_score}", # 客:主
                    "home_score": home_score,
                    "away_score": away_score,
                    "rangfen": rangfen,
                    "yszf": yszf,
                    "sf_result": sf_result,
                    "rfsf_result": rfsf_result,
                    "dxf_result": dxf_result,
                    "total_score": total_score
                })
            except Exception as e:
                logger.warning(f"解析篮球赛果 {match_num} 出错: {e}")
                continue
                
        logger.info(f"成功解析出 {len(results)} 场篮球赛果。")
        return results

if __name__ == "__main__":
    crawler = JclqCrawler()
    matches = crawler.fetch_today_matches()
    for m in matches[:3]:
        print(m)
