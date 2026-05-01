import requests
from bs4 import BeautifulSoup

url = 'https://odds.500.com/fenxi/shuju-1205427.shtml'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
res = requests.get(url, headers=headers)
res.encoding = 'gb2312'
soup = BeautifulSoup(res.text, 'html.parser')

# Check if '射门' is in the text
if '射门' in res.text:
    print('Found "射门" in the page text')
else:
    print('No "射门" found')