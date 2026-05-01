import json
import os
import re
import time
from datetime import datetime, timedelta
from loguru import logger
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext


class LeisuCrawler:
    """雷速体育数据爬虫，基于 Playwright 浏览器自动化"""

    COOKIE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               'data', 'leisu_cookies.json')
    BASE_URL = "https://live.leisu.com"
    LOGIN_URLS = [
        "https://www.leisu.com/login",
        "https://www.leisu.com",
    ]

    def __init__(self, headless=True):
        self.username = os.getenv('LEISU_USERNAME', '')
        self.password = os.getenv('LEISU_PASSWORD', '')
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    def _start_browser(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        self._context = self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36'
        )

    def _load_cookies(self):
        if os.path.exists(self.COOKIE_FILE):
            try:
                with open(self.COOKIE_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                self._context.add_cookies(cookies)
                logger.debug(f"已加载 {len(cookies)} 条 Cookie")
                return True
            except Exception as e:
                logger.warning(f"Cookie 加载失败: {e}")
        return False

    def _save_cookies(self):
        os.makedirs(os.path.dirname(self.COOKIE_FILE), exist_ok=True)
        cookies = self._context.cookies()
        with open(self.COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cookies, f)
        logger.info(f"已保存 {len(cookies)} 条 Cookie 到 {self.COOKIE_FILE}")

    def _check_logged_in(self):
        try:
            self._page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=15000)
            self._page.wait_for_timeout(2000)
            html = self._page.content()
            # 登录状态下页面上会有用户相关的元素
            logged_in_markers = ['退出', '个人信息', 'userinfo', 'user-info', 'avatar']
            for marker in logged_in_markers:
                if marker in html:
                    return True
            return False
        except Exception:
            return False

    def _do_login(self):
        for login_url in self.LOGIN_URLS:
            try:
                self._page.goto(login_url, wait_until='domcontentloaded', timeout=15000)
                self._page.wait_for_timeout(3000)
                logger.info(f"登录页面 {login_url} 加载成功")
                break
            except Exception:
                logger.warning(f"登录页面 {login_url} 加载超时，尝试下一个")
                continue
        else:
            logger.warning("所有登录URL均超时，将以未登录模式继续")
            self._logged_in = False
            return False

        # 尝试多种登录表单填充方式
        try:
            # 方式1: 查找手机号/邮箱输入框
            phone_input = self._page.locator('input[placeholder*="手机"], input[placeholder*="邮箱"], input[type="text"]').first
            if phone_input:
                phone_input.fill(self.username)
                self._page.wait_for_timeout(500)
        except Exception:
            pass

        try:
            # 密码输入框
            pwd_input = self._page.locator('input[type="password"]').first
            if pwd_input:
                pwd_input.fill(self.password)
                self._page.wait_for_timeout(500)
        except Exception:
            pass

        try:
            # 点击登录按钮
            login_btn = self._page.locator('button:has-text("登录"), button:has-text("登 录"), .login-btn, [type="submit"]').first
            if login_btn:
                login_btn.click()
                self._page.wait_for_timeout(5000)
        except Exception:
            pass

        # 检测是否出现验证码
        if self._check_captcha():
            logger.warning("检测到验证码，请在浏览器中手动完成验证码后按回车...")
            input()
            self._page.wait_for_timeout(2000)

        if self._check_logged_in():
            self._save_cookies()
            logger.info("雷速体育登录成功")
            self._logged_in = True
            return True

        logger.error("雷速体育登录失败")
        return False

    def _check_captcha(self):
        try:
            page_text = self._page.content()
            captcha_keywords = ['验证码', '滑块', 'captcha', '请完成验证', '请拖动']
            return any(k in page_text for k in captcha_keywords)
        except Exception:
            return False

    def ensure_login(self):
        self._start_browser()
        self._page = self._context.new_page()

        # 尝试加载 Cookie
        if self._load_cookies():
            if self._check_logged_in():
                logger.info("Cookie 有效，登录态已恢复")
                self._logged_in = True
                return True
            logger.info("Cookie 已过期，重新登录")

        if not self.username or not self.password:
            logger.warning("未配置 LEISU_USERNAME/LEISU_PASSWORD，以未登录模式继续")
            self._logged_in = False
            return False  # 浏览器仍可用，只是未登录

        result = self._do_login()
        if not result:
            logger.warning("登录失败，将以未登录模式继续（浏览器仍可用）")
        return result

    def close(self):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # ==================== 比赛搜索与定位 ====================

    GUIDE_URL = "https://www.leisu.com/guide"

    SKIP_PATTERN = re.compile(r'^(\d+:\d+|联赛第\d+轮|分组赛第\d+轮|附加赛\d+第\d+轮|$)$')
    RANK_PATTERN = re.compile(r'^[\u4e00-\u9fa5]+ \d+$')
    LEAGUE_NAMES = ["欧联","欧协联","欧冠","欧罗巴","英超","西甲","德甲","意甲","法甲",
                    "挪超","葡超","荷甲","荷乙","瑞超","美职","美职足","解放者杯",
                    "沙特联","巴西甲","乌拉圭甲","玻利甲","芬超","南美杯","日职","韩K","K2"]

    def fetch_match_data(self, home_team, away_team, match_time=None):
        """从雷速体育获取一场比赛的综合数据。流程: guide页定位match_id → shujufenxi详情页提取"""
        if not self._page:
            if not self.ensure_login():
                return None
        try:
            match_url = self._find_match_page(home_team, away_team)
            if not match_url:
                logger.error(f"未在雷速找到比赛: {home_team} vs {away_team}")
                return None

            logger.info(f"找到比赛页面: {match_url}")
            self._page.goto(match_url, wait_until='domcontentloaded', timeout=60000)
            self._page.wait_for_timeout(5000)

            body = self._page.locator("body").inner_text()

            result = self._extract_all_modules(body)
            result['_url'] = match_url
            return result

        except Exception as e:
            logger.error(f"抓取雷速比赛数据失败: {e}")
            return None

    def _find_match_page(self, home_team, away_team):
        """从 guide 页面竞彩筛选列表中，通过队名匹配找到比赛的 shujufenxi URL"""
        self._page.goto(self.GUIDE_URL, wait_until='domcontentloaded', timeout=60000)
        self._page.wait_for_timeout(4000)
        try:
            self._page.locator("text=竞彩").first.click()
            self._page.wait_for_timeout(3000)
        except Exception:
            pass

        body = self._page.locator("body").inner_text()
        lines = [l.strip() for l in body.split("\n")]

        # 收集 DOM 中的 shujufenxi URL
        all_as = self._page.locator("a[href*='shujufenxi']").all()
        shujufenxi_urls = []
        for a in all_as:
            href = a.get_attribute("href")
            if href:
                full = "https://live.leisu.com" + href if href.startswith("/") else href
                if full not in shujufenxi_urls:
                    shujufenxi_urls.append(full)

        # 从 body 文本按"直播 情报 分析"分割出每场对阵
        match_list = []
        for i, line in enumerate(lines):
            if line == "直播 情报 分析":
                teams = []
                for j in range(i - 1, max(0, i - 20), -1):
                    c = lines[j]
                    if not c or self.SKIP_PATTERN.match(c) or self.RANK_PATTERN.match(c) or c in self.LEAGUE_NAMES:
                        continue
                    teams.append(c)
                    if len(teams) == 2:
                        break
                if len(teams) == 2:
                    match_list.append((teams[1], teams[0]))

        # 匹配目标队名
        target_idx = None
        for i, (h, a) in enumerate(match_list):
            if home_team in h or home_team in a:
                target_idx = i
                break
        if target_idx is None:
            for i, (h, a) in enumerate(match_list):
                if away_team in h or away_team in a:
                    target_idx = i
                    break

        if target_idx is not None and target_idx < len(shujufenxi_urls):
            return shujufenxi_urls[target_idx]
        return None

    def _extract_all_modules(self, body):
        """从 shujufenxi 详情页 body 文本中按模块切分提取"""
        result = {}
        blocks = ["历史交锋", "近期战绩", "联赛积分", "进球分布", "伤停情况", "半全场胜负"]
        sections = {}
        pos_list = [(b, body.find(b)) for b in blocks if body.find(b) >= 0]
        pos_list.sort(key=lambda x: x[1])
        for i, (name, p) in enumerate(pos_list):
            end = pos_list[i + 1][1] if i + 1 < len(pos_list) else len(body)
            sections[name] = body[p + len(name):end].strip()

        # 伤停
        if "伤停情况" in sections:
            # 截断到"近期赛程"之前
            injury_text = sections["伤停情况"]
            rc_pos = injury_text.find("近期赛程")
            if rc_pos > 0:
                injury_text = injury_text[:rc_pos]
            result['injuries'] = injury_text.strip()[:800]

        # 联赛积分 → standings
        if "联赛积分" in sections:
            ranks = re.findall(r'\[.*?(\d+)\]', sections["联赛积分"])
            result['standings'] = ranks[:6]

        # 进球分布
        if "进球分布" in sections:
            nums = [int(x) for x in re.findall(r'\d+', sections["进球分布"])]
            result['goal_distribution'] = nums[:24]

        # 半全场
        if "半全场胜负" in sections:
            htft = {}
            for label in ["胜胜","胜平","胜负","平胜","平平","平负","负胜","负平","负负"]:
                m = re.search(f'{label}\\s*(\\d+)', sections["半全场胜负"])
                if m:
                    htft[label] = int(m.group(1))
            if htft:
                result['htft'] = htft

        # 历史交锋
        if "历史交锋" in sections:
            scores = re.findall(r'(\d+)\s*:\s*(\d+)', sections["历史交锋"])
            result['h2h_scores'] = [f"{s[0]}-{s[1]}" for s in scores]

        # 近期战绩
        if "近期战绩" in sections:
            scores = re.findall(r'(\d+)\s*:\s*(\d+)', sections["近期战绩"])
            result['recent_scores'] = [f"{s[0]}-{s[1]}" for s in scores]

        return result


if __name__ == "__main__":
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(base_dir, "config", ".env"))

    crawler = LeisuCrawler(headless=False)
    try:
        crawler.ensure_login()
        data = crawler.fetch_match_data("布拉加", "弗赖堡")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    finally:
        crawler.close()
