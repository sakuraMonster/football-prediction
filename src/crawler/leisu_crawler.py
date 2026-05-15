import json
import os
import sys
import re
import time
import asyncio
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from loguru import logger
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import nest_asyncio

# 解决在 Streamlit 或已存在的事件循环中调用 Playwright 同步 API 报错的问题
nest_asyncio.apply()

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
        self.username = ''
        self.password = ''
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False
        self._executor = None
        self._owner_thread_ident = None
        self._anonymous_mode = True

    def _ensure_executor(self):
        if self._executor is None:
            # 在专用线程里运行 Playwright，同线程复用浏览器对象，规避 Streamlit 脚本线程的事件循环冲突
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leisu-playwright")

    def _should_use_worker_thread(self):
        # Streamlit 的脚本线程在 Windows 下即便没有“running loop”，
        # 也可能处于不适合直接启动 Playwright 子进程的上下文中。
        # 因此除了工作线程自身外，统一转发到专用线程执行。
        return threading.get_ident() != self._owner_thread_ident

    def _run_in_worker(self, func, *args, **kwargs):
        self._ensure_executor()
        future = self._executor.submit(func, *args, **kwargs)
        return future.result()

    def _start_browser(self):
        self._owner_thread_ident = threading.get_ident()
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
        if self._page:
            return True
        self._start_browser()
        self._page = self._context.new_page()
        if self._anonymous_mode:
            logger.info("雷速体育使用匿名模式抓取数据，无需登录")
            self._logged_in = False
            return True

        # 以下登录逻辑目前保留但默认不启用
        if self._load_cookies():
            if self._check_logged_in():
                logger.info("Cookie 有效，登录态已恢复")
                self._logged_in = True
                return True
            logger.info("Cookie 已过期，重新登录")

        result = self._do_login()
        if not result:
            logger.warning("登录失败，将以匿名模式继续抓取雷速数据")
            self._logged_in = False
        return True

    def close(self):
        if self._executor and self._owner_thread_ident is not None and threading.get_ident() != self._owner_thread_ident:
            try:
                self._run_in_worker(self.close)
            finally:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
            return
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
        self._owner_thread_ident = None

    # ==================== 比赛搜索与定位 ====================

    GUIDE_URL = "https://www.leisu.com/guide"

    SKIP_PATTERN = re.compile(r'^(\d+:\d+|联赛第\d+轮|分组赛第\d+轮|附加赛\d+第\d+轮|$)$')
    RANK_PATTERN = re.compile(r'^[\u4e00-\u9fa5]+ \d+$')
    LEAGUE_NAMES = ["欧联","欧协联","欧冠","欧罗巴","英超","西甲","德甲","意甲","法甲",
                    "挪超","葡超","荷甲","荷乙","瑞超","美职","美职足","解放者杯",
                    "沙特联","巴西甲","乌拉圭甲","玻利甲","芬超","南美杯","日职","韩K","K2"]

    @staticmethod
    def _extract_match_page_id(url):
        if not url:
            return None
        match = re.search(r'-(\d+)(?:[/?#]|$)', str(url))
        return match.group(1) if match else None

    @classmethod
    def _build_swot_url_from_analysis(cls, analysis_url):
        match_id = cls._extract_match_page_id(analysis_url)
        if not match_id:
            return None
        return f"https://www.leisu.com/guide/swot-{match_id}"

    def fetch_match_data(self, home_team, away_team, match_time=None):
        try:
            if self._should_use_worker_thread():
                return self._run_in_worker(self._fetch_match_data_internal, home_team, away_team, match_time)
            return self._fetch_match_data_internal(home_team, away_team, match_time)
        except NotImplementedError as e:
            # Windows + Streamlit + Playwright Sync API 在部分环境下仍可能触发
            # asyncio 子进程实现冲突，此时退回到独立 Python 进程隔离执行。
            logger.warning(f"当前进程内启动 Playwright 失败，切换到子进程抓取雷速数据: {e}")
            return self._fetch_match_data_via_subprocess(home_team, away_team, match_time)

    def _fetch_match_data_via_subprocess(self, home_team, away_team, match_time=None):
        env = os.environ.copy()
        env["LEISU_SUBPROCESS_MODE"] = "1"
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            "--fetch-json",
            home_team,
            away_team,
            match_time or "",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            raise RuntimeError(f"雷速子进程抓取失败(exit={result.returncode}): {stderr or stdout}")

        stdout = (result.stdout or "").strip()
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if not lines:
                return None
            return json.loads(lines[-1])

    def _fetch_match_data_internal(self, home_team, away_team, match_time=None):
        """从雷速体育获取一场比赛的综合数据。流程: guide页定位比赛 → 分析页/情报页提取"""
        if not self._page:
            if not self.ensure_login():
                return None
        try:
            match_pages = self._find_match_pages(home_team, away_team)
            match_url = match_pages.get("analysis_url")
            if not match_url:
                logger.error(f"未在雷速找到比赛: {home_team} vs {away_team}")
                return None

            logger.info(f"找到比赛页面: {match_url}")
            self._page.goto(match_url, wait_until='domcontentloaded', timeout=60000)
            self._page.wait_for_timeout(5000)

            body = self._page.locator("body").inner_text()

            result = self._extract_all_modules(body)
            result['_url'] = match_url
            swot_url = match_pages.get("swot_url")
            if swot_url:
                try:
                    logger.info(f"找到雷速情报页: {swot_url}")
                    self._page.goto(swot_url, wait_until='domcontentloaded', timeout=60000)
                    self._page.wait_for_timeout(3000)
                    swot_body = self._page.locator("body").inner_text()
                    match_swot = self._extract_swot_modules(swot_body, home_team, away_team)
                    if match_swot:
                        result["match_intelligence"] = match_swot
                        result["_swot_url"] = swot_url
                except Exception as swot_error:
                    logger.warning(f"抓取雷速情报页失败: {swot_error}")
            return result

        except Exception as e:
            logger.error(f"抓取雷速比赛数据失败: {e}")
            return None

    def _find_match_pages(self, home_team, away_team):
        """从 guide 页面竞彩筛选列表中，通过队名匹配找到比赛的分析页和情报页 URL"""
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

        # 收集 DOM 中的 swot 情报 URL
        all_swot_as = self._page.locator("a[href*='swot-']").all()
        swot_urls = []
        swot_url_by_id = {}
        for a in all_swot_as:
            href = a.get_attribute("href")
            if href:
                if href.startswith("/"):
                    full = "https://www.leisu.com" + href
                elif href.startswith("http"):
                    full = href
                else:
                    full = "https://www.leisu.com/" + href.lstrip("/")
                if full not in swot_urls:
                    swot_urls.append(full)
                match_id = self._extract_match_page_id(full)
                if match_id and match_id not in swot_url_by_id:
                    swot_url_by_id[match_id] = full

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

        if target_idx is None:
            return {}

        result = {}
        if target_idx < len(shujufenxi_urls):
            analysis_url = shujufenxi_urls[target_idx]
            result["analysis_url"] = analysis_url
            analysis_match_id = self._extract_match_page_id(analysis_url)
            if analysis_match_id and swot_url_by_id.get(analysis_match_id):
                result["swot_url"] = swot_url_by_id[analysis_match_id]
            else:
                derived_swot_url = self._build_swot_url_from_analysis(analysis_url)
                if derived_swot_url:
                    result["swot_url"] = derived_swot_url
        elif target_idx < len(swot_urls):
            result["swot_url"] = swot_urls[target_idx]
        return result

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

    @staticmethod
    def _split_swot_points(text, limit=4):
        if not text:
            return []
        cleaned = re.sub(r'\s+', ' ', text).strip(" \n\r\t：:")
        cleaned = re.sub(r'^[^\u4e00-\u9fa5A-Za-z0-9%]+', '', cleaned)
        cleaned = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9%]+$', '', cleaned)
        if not cleaned:
            return []
        parts = re.split(r'[。！？；;]+', cleaned)
        points = []
        for part in parts:
            item = part.strip(" \n\r\t：:")
            if item and item not in points:
                points.append(item)
            if len(points) >= limit:
                break
        return points

    @staticmethod
    def _clean_swot_body_text(body):
        text = re.sub(r'\s+', ' ', body or '').strip()
        if not text:
            return ""

        noise_markers = [
            "热门推荐",
            "热门雷速推荐",
            "查看更多",
            "关于雷速",
            "网站地图",
            "商务合作",
            "免费直播调用",
            "用户服务协议",
            "隐私政策",
            "Copyright",
            "Leisu.ALL Rights Reserved",
            "微信扫描二维码",
            "联系在线客服",
            "内容仅供参考",
            "以上各种走势数据截止时间",
            "本文由",
            "欢迎分享本文",
        ]
        for marker in noise_markers:
            pos = text.find(marker)
            if pos >= 0:
                text = text[:pos].strip()

        return text

    @staticmethod
    def _extract_team_label(prefix_text, fallback=""):
        if not prefix_text:
            return fallback

        compact = prefix_text.strip()
        candidates = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9·\-]{2,20}', compact)
        blacklist = {
            "首页", "体育直播", "赛事推荐", "资讯中心", "资料库", "数据服务", "APP下载",
            "自媒体", "登录", "注册", "情报对比", "走势分析", "联赛排名", "赛果概率",
            "历史交锋", "近期战绩", "查看数据分析", "进入聊天室", "半决赛", "欧联",
            "欧罗巴", "欧协联", "欧冠"
        }
        filtered = []
        for candidate in candidates:
            if candidate in blacklist:
                continue
            if re.fullmatch(r'\d+(?:-\d+)?|[0-9:%]+', candidate):
                continue
            filtered.append(candidate)

        if not filtered:
            return fallback
        return filtered[-1]

    @classmethod
    def _extract_swot_modules(cls, body, home_team="", away_team=""):
        """从雷速 swot 页面提取主客有利/不利与中立情报。"""
        text = cls._clean_swot_body_text(body)
        if not text or "有利情报" not in text or "不利情报" not in text:
            return {}

        marker = "有利情报"
        first_marker = text.find(marker)
        second_marker = text.find(marker, first_marker + len(marker))
        neutral_marker = text.find("中立情报")
        first_negative = text.find("不利情报", first_marker + len(marker))
        second_negative = text.find("不利情报", second_marker + len(marker)) if second_marker >= 0 else -1

        if min(first_marker, second_marker, neutral_marker, first_negative, second_negative) < 0:
            return {}

        home_prefix = text[:first_marker]
        away_prefix = text[neutral_marker + len("中立情报"):second_marker]
        extracted_home = cls._extract_team_label(home_prefix, home_team or "")
        extracted_away = cls._extract_team_label(away_prefix, away_team or "")
        home_label = extracted_home
        away_label = extracted_away
        if home_team and extracted_home and home_team in extracted_home and len(extracted_home) > len(home_team):
            home_label = extracted_home
        elif home_team:
            home_label = home_team
        if away_team and extracted_away and away_team in extracted_away and len(extracted_away) > len(away_team):
            away_label = extracted_away
        elif away_team:
            away_label = away_team
        home_pros = cls._split_swot_points(text[first_marker + len(marker):first_negative])
        home_cons = cls._split_swot_points(text[first_negative + len("不利情报"):neutral_marker])
        neutral_text = text[neutral_marker + len("中立情报"):second_marker]
        if away_team and neutral_text.endswith(away_team):
            neutral_text = neutral_text[: -len(away_team)]
        neutral = cls._split_swot_points(neutral_text, limit=3)
        away_pros = cls._split_swot_points(text[second_marker + len(marker):second_negative])
        away_cons = cls._split_swot_points(text[second_negative + len("不利情报"):])

        if home_team and home_team in away_label and away_team:
            away_label = away_team
        if away_team and away_team not in away_label and away_team in text[second_marker - 20:second_marker + 20]:
            away_label = away_team

        if not any([home_pros, home_cons, away_pros, away_cons, neutral]):
            return {}

        return {
            "home_team": home_label,
            "away_team": away_label,
            "home": {"pros": home_pros, "cons": home_cons},
            "away": {"pros": away_pros, "cons": away_cons},
            "neutral": neutral,
        }


if __name__ == "__main__":
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(base_dir, "config", ".env"))

    if len(sys.argv) >= 4 and sys.argv[1] == "--fetch-json":
        home_team = sys.argv[2]
        away_team = sys.argv[3]
        match_time = sys.argv[4] if len(sys.argv) >= 5 else None
        crawler = LeisuCrawler(headless=True)
        try:
            data = crawler._fetch_match_data_internal(home_team, away_team, match_time)
            print(json.dumps(data, ensure_ascii=False))
        finally:
            crawler.close()
        sys.exit(0)

    crawler = LeisuCrawler(headless=False)
    try:
        crawler.ensure_login()
        data = crawler.fetch_match_data("布拉加", "弗赖堡")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    finally:
        crawler.close()
