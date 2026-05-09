import sys
import types

playwright = types.ModuleType('playwright')
sync_api = types.ModuleType('playwright.sync_api')
sync_api.sync_playwright = lambda: None
sync_api.Page = object
sync_api.Browser = object
sync_api.BrowserContext = object
playwright.sync_api = sync_api
sys.modules['playwright'] = playwright
sys.modules['playwright.sync_api'] = sync_api

from src.crawler.leisu_crawler import LeisuCrawler

text = '斯特拉斯堡有利情报斯特拉斯堡身价巴列卡诺身价的3倍，斯特拉斯堡阵容实力对巴列卡诺有一定优势。斯特拉斯堡近10场正赛多达8场比赛半场有得失球。不利情报斯特拉斯堡首回合客场0比1告负，总比分落后1球。斯特拉斯堡本场比赛继续面临人员不整问题。轮换后卫安塞尔米诺和主力前锋帕尼切利仍因伤缺席。中立情报斯洛伐克裁判伊万克鲁日利亚克将执法本场斯特拉斯堡对阵巴列卡诺的欧协联比赛。巴列卡诺有利情报近6场欧协联比赛来看，巴列卡诺进攻端斩获11球表现相当惊艳。不利情报巴列卡诺此役遭遇攻防两端减员，主力中卫费利佩与主力边锋加西亚双双伤缺。'
parsed = LeisuCrawler._extract_swot_modules(text, '斯特拉斯', '巴列卡诺')
print(parsed)
assert parsed['home_team'] == '斯特拉斯堡'
assert parsed['away_team'] == '巴列卡诺'
assert parsed['home']['pros']
assert parsed['home']['cons']
assert parsed['away']['pros']
assert parsed['away']['cons']
assert parsed['neutral']
print('SWOT_OK')
