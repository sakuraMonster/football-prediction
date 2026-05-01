import requests

url = 'https://www.dongqiudi.com/api/search/all?keywords=曼联&type=team'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.dongqiudi.com/',
    'Accept': 'application/json, text/plain, */*'
}
res = requests.get(url, headers=headers)
print(f"Status: {res.status_code}")
if res.status_code == 200:
    print(res.text[:500])
else:
    print(res.text[:500])