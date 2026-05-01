from bs4 import BeautifulSoup
import requests

url = 'http://odds.500.com/fenxi/shuju-1216051.shtml'
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
resp.encoding = 'gb2312'
soup = BeautifulSoup(resp.text, 'html.parser')

print(soup.title.text)
tables = soup.find_all('table')
for t in tables:
    if 'id' in t.attrs and 'team_zhanji' not in t['id']:
        print(t['id'])
    elif 'class' in t.attrs:
        print(t['class'])
        
# Find technic stats table
div = soup.find('div', {'id': 'technic'})
if div:
    print("Found technic!")
    print(div.text[:500])
else:
    print("No technic div")
