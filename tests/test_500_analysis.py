import requests
from bs4 import BeautifulSoup

def test_500_analysis():
    fixture_id = "1205427"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 1. 抓取基本面数据 (近期战绩, 交锋)
    shuju_url = f"https://odds.500.com/fenxi/shuju-{fixture_id}.shtml"
    res = requests.get(shuju_url, headers=headers)
    res.encoding = 'gb2312'
    
    soup = BeautifulSoup(res.text, 'html.parser')
    
    print("--- 历史交锋 ---")
    # find the H2H table, usually there is a table with class "pub_table"
    # let's just save it to file to inspect first
    with open("tests/500_shuju.html", "w", encoding="utf-8") as f:
        f.write(res.text)
        
    print("已保存 shuju 页面到 tests/500_shuju.html")
    
    # 2. 抓取亚盘数据
    yazhi_url = f"https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml"
    res2 = requests.get(yazhi_url, headers=headers)
    res2.encoding = 'gb2312'
    with open("tests/500_yazhi.html", "w", encoding="utf-8") as f:
        f.write(res2.text)
        
    print("已保存 yazhi 页面到 tests/500_yazhi.html")

if __name__ == "__main__":
    test_500_analysis()
