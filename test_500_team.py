import requests
from bs4 import BeautifulSoup

url = 'https://liansai.500.com/team/462/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
res = requests.get(url, headers=headers)
res.encoding = 'gb2312'
print(f"Status: {res.status_code}")
if '场均' in res.text or '射门' in res.text:
    print("Found stats!")
else:
    print("No stats found in search result.")