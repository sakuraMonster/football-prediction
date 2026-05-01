import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

print("=== 雷速体育 v11 最终版 ===\n")

from src.crawler.leisu_crawler import LeisuCrawler

crawler = LeisuCrawler(headless=True)
try:
    crawler._start_browser()
    page = crawler._context.new_page()
    page.goto("https://www.leisu.com/guide", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.locator("text=竞彩").first.click()
    page.wait_for_timeout(3000)

    body = page.locator("body").inner_text()
    lines = [l.strip() for l in body.split("\n")]

    # Step 1: 收集 shujufenxi URL（DOM顺序）
    all_as = page.locator("a[href*='shujufenxi']").all()
    shujufenxi_urls = []
    for a in all_as:
        href = a.get_attribute("href")
        if href:
            full = "https://live.leisu.com" + href if href.startswith("/") else href
            if full not in shujufenxi_urls:
                shujufenxi_urls.append(full)

    # Step 2: 从 body 文本中按"直播 情报 分析"分割出每场对阵
    skip_pattern = re.compile(r'^(\d+:\d+|联赛第\d+轮|分组赛第\d+轮|附加赛\d+第\d+轮|$)$')
    rank_pattern = re.compile(r'^[\u4e00-\u9fa5]+ \d+$')  # like "葡超 4", "德甲 8"
    league_names = ["欧联","欧协联","英超","西甲","德甲","意甲","法甲","挪超","葡超",
                    "荷甲","荷乙","瑞超","美职","解放者杯","沙特联","巴西甲","乌拉圭甲","玻利甲","芬超"]

    match_list = []
    for i, line in enumerate(lines):
        if line == "直播 情报 分析":
            # 往前找两个队名
            teams = []
            for j in range(i-1, max(0, i-20), -1):
                c = lines[j]
                if not c or skip_pattern.match(c) or rank_pattern.match(c) or c in league_names:
                    continue
                teams.append(c)
                if len(teams) == 2:
                    break
            if len(teams) == 2:
                match_list.append((teams[1], teams[0]))

    print(f"识别到 {len(match_list)} 场比赛 (URL共{len(shujufenxi_urls)}):")
    target_idx = None
    for i, (h, a) in enumerate(match_list):
        marker = " <===" if "布拉加" in h else ""
        print(f"  [{i}] {h} vs {a}{marker}")
        if "布拉加" in h:
            target_idx = i

    if target_idx is None or target_idx >= len(shujufenxi_urls):
        raise SystemExit(f"失败: idx={target_idx}")

    target_url = shujufenxi_urls[target_idx]
    print(f"\n>>> 布拉加 idx={target_idx} => {target_url.split('/')[-1]}")

    # Step 3: 访问详情页
    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    body2 = page.locator("body").inner_text()
    print(f"详情页: {len(body2)} 字符")

    result = {"url": target_url}

    # 模块切分
    blocks = ["历史交锋", "近期战绩", "联赛积分", "进球分布", "伤停情况", "半全场胜负"]
    sections = {}
    pos_list = [(b, body2.find(b)) for b in blocks if body2.find(b) >= 0]
    pos_list.sort(key=lambda x: x[1])
    for i, (name, p) in enumerate(pos_list):
        end = pos_list[i+1][1] if i+1 < len(pos_list) else len(body2)
        sections[name] = body2[p+len(name):end].strip()[:800]

    # 伤停
    if "伤停情况" in sections:
        result["injuries"] = sections["伤停情况"][:500]
        print(f"\n  [伤停]: {result['injuries'][:250]}")

    # 积分
    if "联赛积分" in sections:
        ranks = re.findall(r'\[.*?(\d+)\]', sections["联赛积分"])
        result["standings"] = ranks[:6]
        print(f"  [排名]: {ranks[:6]}")

    # 进球分布
    if "进球分布" in sections:
        nums = re.findall(r'(\d+)', sections["进球分布"])[:18]
        result["goal_dist"] = nums
        print(f"  [进球分布]: {nums}")

    # 半全场
    if "半全场胜负" in sections:
        htft = {}
        for label in ["胜胜","胜平","胜负","平胜","平平","平负","负胜","负平","负负"]:
            m = re.search(f'{label}\\s*(\\d+)', sections["半全场胜负"])
            if m:
                htft[label] = int(m.group(1))
        result["htft"] = htft
        print(f"  [半全场]: {htft}")

    # 交锋
    if "历史交锋" in sections:
        scores = re.findall(r'(\d+)\s*:\s*(\d+)', sections["历史交锋"])
        result["h2h_scores"] = [f"{s[0]}-{s[1]}" for s in scores]
        print(f"  [交锋]: {result['h2h_scores']}")

    # 近期
    if "近期战绩" in sections:
        scores = re.findall(r'(\d+)\s*:\s*(\d+)', sections["近期战绩"])
        result["recent_scores"] = [f"{s[0]}-{s[1]}" for s in scores]
        print(f"  [近期]: {len(result['recent_scores'])}组")

    print(f"\n{'='*50}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])

finally:
    crawler.close()
    print("\n浏览器已关闭")
