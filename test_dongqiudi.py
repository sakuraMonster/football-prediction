import requests
import re
import json

url = 'https://www.dongqiudi.com/team/50000512.html'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
res = requests.get(url, headers=headers)
match = re.search(r'window\.__NUXT__=(.*?);</script>', res.text)
if match:
    data = match.group(1)
    
    # 找场均射门，一般是 shots_per_game, shots, 等等
    # 懂球帝的NUXT可能把键压缩了
    # 我们可以搜索包含这些词的上下文
    shots = re.findall(r'.{0,30}shots.{0,30}', data, re.IGNORECASE)
    print('Shots context:')
    for s in set(shots[:10]):
        print(s)
        
    goals = re.findall(r'.{0,30}goals.{0,30}', data, re.IGNORECASE)
    print('\nGoals context:')
    for g in set(goals[:10]):
        print(g)