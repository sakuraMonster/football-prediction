import requests

url = 'https://api.dongqiudi.com/data/v1/team/50000512'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
res = requests.get(url, headers=headers)
print(f"Status: {res.status_code}")
if res.status_code == 200:
    print(res.text[:500])