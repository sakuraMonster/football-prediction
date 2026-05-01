import requests

url = 'https://www.okooo.com/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
res = requests.get(url, headers=headers)
print(f"Status: {res.status_code}")