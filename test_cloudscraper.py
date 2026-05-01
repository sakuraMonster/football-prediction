import cloudscraper

scraper = cloudscraper.create_scraper()
url = 'https://www.dongqiudi.com/api/search/all?keywords=曼联&type=team'
res = scraper.get(url, headers={'Referer': 'https://www.dongqiudi.com/'})
print(f"Status: {res.status_code}")
if res.status_code == 200:
    print(res.text[:500])
else:
    print(res.text[:500])