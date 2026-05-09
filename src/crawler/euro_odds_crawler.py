import requests
from bs4 import BeautifulSoup
from loguru import logger
import re
import time


class EuroOddsCrawler:
    """从500.com欧赔分析页提取初赔和临赔数据"""

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }

    def fetch_euro_odds(self, fixture_id, retries=3, delay=2.0, max_companies=5):
        """
        从 odds.500.com/fenxi/ouzhi-{fixture_id}.shtml 的 AJAX 接口提取初赔和临赔。
        返回: list of dict，每项包含 company, init_home, init_draw, init_away, live_home, live_draw, live_away
        500.com有速率限制，内置重试+间隔机制。
        max_companies: 仅保留前N家主流公司（默认5：竞彩官方/威廉希尔/澳门/立博/bet365）
        """
        url = f"https://odds.500.com/fenxi1/ouzhi.php?id={fixture_id}&ctype=1&start=0&r=1&guojia=1&chupan=1"
        referer = f"https://odds.500.com/fenxi/ouzhi-{fixture_id}.shtml"
        req_headers = {**self.headers, "Referer": referer}

        for attempt in range(retries):
            try:
                if attempt > 0:
                    wait = delay * (attempt + 1)  # 递增等待: 2s -> 4s -> 6s
                    logger.debug(f"fixture_id={fixture_id} 第{attempt+1}次重试，等待{wait}s...")
                    time.sleep(wait)

                r = requests.get(url, headers=req_headers, timeout=15)
                r.encoding = 'gb2312'

                soup = BeautifulSoup(r.text, 'html.parser')
                datatb = soup.find('table', id='datatb')
                if not datatb:
                    if attempt < retries - 1:
                        logger.warning(f"fixture_id={fixture_id} 未找到 datatb 表格 (第{attempt+1}次)，可能被限流，将重试...")
                        continue
                    else:
                        logger.warning(f"fixture_id={fixture_id} 重试{retries}次后仍未找到 datatb 表格，跳过")
                        return []

                rows = datatb.find_all('tr', attrs={'xls': 'row'})
                if not rows:
                    if attempt < retries - 1:
                        logger.warning(f"fixture_id={fixture_id} datatb 无数据行 (第{attempt+1}次)，将重试...")
                        continue
                    else:
                        return []

                results = []
                for row in rows:
                    company_el = row.find('span', class_='guojia')
                    if not company_el:
                        continue
                    company = company_el.text.strip()

                    sub_tables = row.find_all('table', class_='pl_table_data')
                    if len(sub_tables) < 1:
                        continue

                    odds_table = sub_tables[0]
                    trs = odds_table.find_all('tr')
                    if len(trs) < 2:
                        continue

                    init_tds = trs[0].find_all('td')
                    live_tds = trs[1].find_all('td')

                    if len(init_tds) < 3 or len(live_tds) < 3:
                        continue

                    init_home = init_tds[0].text.strip()
                    init_draw = init_tds[1].text.strip()
                    init_away = init_tds[2].text.strip()
                    live_home = live_tds[0].text.strip()
                    live_draw = live_tds[1].text.strip()
                    live_away = live_tds[2].text.strip()

                    if not re.match(r'^\d+\.\d+$', init_home):
                        continue

                    results.append({
                        "company": company,
                        "init_home": init_home,
                        "init_draw": init_draw,
                        "init_away": init_away,
                        "live_home": live_home,
                        "live_draw": live_draw,
                        "live_away": live_away,
                    })

                if max_companies and len(results) > max_companies:
                    results = results[:max_companies]

                logger.info(f"fixture_id={fixture_id} 提取到 {len(results)} 家公司欧赔数据 (尝试{attempt+1}次)")
                return results

            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"fixture_id={fixture_id} 请求异常 (第{attempt+1}次): {e}，将重试...")
                    time.sleep(delay)
                else:
                    logger.error(f"fixture_id={fixture_id} 重试{retries}次后仍失败: {e}")
                    return []


if __name__ == "__main__":
    crawler = EuroOddsCrawler()
    odds = crawler.fetch_euro_odds("1337828")
    for o in odds[:3]:
        print(f"{o['company']}: init({o['init_home']},{o['init_draw']},{o['init_away']}) → live({o['live_home']},{o['live_draw']},{o['live_away']})")
