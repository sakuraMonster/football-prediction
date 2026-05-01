import urllib.request
import json

url = 'https://api.dongqiudi.com/data/v1/team/50000512'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
try:
    with urllib.request.urlopen(req) as response:
        print(response.status)
        print(response.read().decode('utf-8')[:500])
except Exception as e:
    print(e)