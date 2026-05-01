import requests

url = 'https://www.dongqiudi.com/team/50000512.html'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
res = requests.get(url, headers=headers)
with open('dqd_team.html', 'w', encoding='utf-8') as f:
    f.write(res.text)