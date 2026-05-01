import requests
from bs4 import BeautifulSoup
url = "https://trade.500.com/sfc/"
headers = {"User-Agent": "Mozilla/5.0"}
r = requests.get(url, headers=headers)
r.encoding = 'gb2312'
soup = BeautifulSoup(r.text, 'html.parser')
# Find any elements containing the word "期"
tags = soup.find_all(text=lambda text: text and '期' in text)
print("Tags with '期':")
for t in tags[:10]:
    print(t.parent.name, t.parent.attrs, t.strip())

# Look for specific selectors
print("\nLooking for 'expect' select:")
select = soup.find('select', id='expect')
if select:
    print(select)
else:
    print("Not found")

print("\nLooking for data-expect attributes:")
links = soup.find_all('a', attrs={'data-expect': True})
if links:
    print(links[0].get('data-expect'))
else:
    print("Not found")
