import requests
from bs4 import BeautifulSoup

def test_500_crawler():
    url = "https://trade.500.com/jczq/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    response.encoding = 'gb2312' # 500.com usually uses gb2312
    
    if response.status_code != 200:
        print(f"HTTP Error: {response.status_code}")
        return
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 查找比赛行
    match_rows = soup.find_all('tr', class_='bet-tb-tr')
    print(f"找到 {len(match_rows)} 场比赛\n")
    
    if len(match_rows) == 0:
        print("未找到比赛，保存页面源码...")
        with open("tests/500_page.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        return
    
    for row in match_rows[:5]: # 只打印前5场
        try:
            match_num = row.get('data-matchnum', '')
            league = row.get('data-simpleleague', '')
            home_team = row.get('data-homesxname', '')
            away_team = row.get('data-awaysxname', '')
            match_time = row.get('data-matchtime', '')
            
            # 赔率解析
            # 非让球胜平负
            nspf_btns = row.find_all('p', {'data-type': 'nspf'})
            nspf_sp = [btn.get('data-sp', '-') for btn in nspf_btns]
            
            # 让球胜平负
            spf_btns = row.find_all('p', {'data-type': 'spf'})
            spf_sp = [btn.get('data-sp', '-') for btn in spf_btns]
            
            rangqiu = row.get('data-rangqiu', '')
                
            print(f"[{match_num}] {league} | {home_team} VS {away_team} | 时间: {match_time}")
            print(f"  -> 不让球: {nspf_sp} | 让球({rangqiu}): {spf_sp}")
        except Exception as e:
            print(f"解析出错: {e}")

if __name__ == "__main__":
    test_500_crawler()
