import requests
from bs4 import BeautifulSoup
import urllib.parse

def search_team_500(team_name):
    # Try to find team on 500.com
    url = f"https://search.500.com/?c=footdata&a=team&k={urllib.parse.quote(team_name.encode('gb2312'))}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    res = requests.get(url, headers=headers)
    res.encoding = 'gb2312'
    print(f"Status: {res.status_code}")
    if '场均' in res.text or '射门' in res.text:
        print("Found stats!")
    else:
        print("No stats found in search result.")
        
search_team_500('曼联')