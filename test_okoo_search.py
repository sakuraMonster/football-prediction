import requests

url = 'https://www.okooo.com/search/?word=曼联'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
res = requests.get(url, headers=headers)
res.encoding = 'gb2312'
print(f"Status: {res.status_code}")
if '曼联' in res.text:
    print("Found 曼联 in text!")