import requests
from bs4 import BeautifulSoup
import datetime

url = "https://trade.500.com/jczq/?date=2026-03-29"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
response = requests.get(url, headers=headers)
response.encoding = 'gb2312'
soup = BeautifulSoup(response.text, 'html.parser')
rows = soup.find_all('tr', class_='bet-tb-tr')
print(f"Match rows: {len(rows)}")
for row in rows[:5]:
    match_num = row.get('data-matchnum', '')
    home = row.get('data-homesxname', '')
    away = row.get('data-awaysxname', '')
    score = row.find('a', class_='score')
    score_text = score.text.strip() if score else ""
    print(f"{match_num} {home} vs {away} - Score: {score_text}")
