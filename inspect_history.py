import requests
url = "https://trade.500.com/jczq/?playid=269&g=2&date=2026-04-26"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
r = requests.get(url, headers=headers, timeout=15)
r.encoding = 'gb2312'

# Find bet-tb-tr rows
from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, 'html.parser')
rows = soup.find_all('tr', class_='bet-tb-tr')
print(f"Found {len(rows)} bet-tb-tr rows\n")

for row in rows[:3]:
    mn = row.get('data-matchnum', '')
    fid = row.get('data-fixtureid', '')
    league = row.get('data-simpleleague', '')
    home = row.get('data-homesxname', '')
    away = row.get('data-awaysxname', '')
    mt = row.get('data-matchtime', '')
    md = row.get('data-matchdate', '')
    print(f"  {mn} [{league}] {home} vs {away} | {md} {mt}")

    # Check for score elements (betbtn-ok class)
    for btn in row.find_all('p', class_='betbtn-ok'):
        dtype = btn.get('data-type', '')
        dval = btn.get('data-value', '')
        dsp = btn.get('data-sp', '')
        print(f"    OK: type={dtype} val={dval} sp={dsp}")

    # Check for nspf/spf buttons  
    for btn in row.find_all('p', {'data-type': ['nspf', 'spf']}):
        dtype = btn.get('data-type', '')
        dsp = btn.get('data-sp', '')
        print(f"    ODD: type={dtype} sp={dsp}")

    print()

# Show raw HTML of first row
if rows:
    print("=== RAW 1st row HTML (first 1500 chars) ===")
    print(str(rows[0])[:1500])
