import requests

def test_jingcai_api():
    url = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?poolCode=&channel=c"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"HTTP Error: {response.status_code}")
        
        try:
            data = response.json()
        except ValueError:
            print("Response is not JSON. Content:")
            print(response.text[:500])
            return
        print("API 调用成功！")
        
        matches = data.get("value", {}).get("matchInfoList", [])
        print(f"今日可购买比赛数量: {len(matches)}")
        
        for i, match in enumerate(matches[:3]):  # 打印前3场
            sub_matches = match.get("subMatchList", [])
            for sub_match in sub_matches:
                print(f"[{sub_match['matchNumStr']}] {sub_match['leagueName']} | {sub_match['homeTeamName']} VS {sub_match['awayTeamName']}")
                
    except Exception as e:
        print(f"API 调用失败: {e}")

if __name__ == "__main__":
    test_jingcai_api()
