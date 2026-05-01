from bs4 import BeautifulSoup

def extract_yazhi():
    with open("tests/500_yazhi.html", "r", encoding="utf-8") as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    tables = soup.find_all('table')
    for idx, table in enumerate(tables):
        print(f"Table {idx}, id={table.get('id', '')}, class={table.get('class', '')}")
        rows = table.find_all('tr')
        if rows:
            print("  Row 0:", [td.text.strip() for td in rows[0].find_all(['td', 'th'])])
        if len(rows) > 1:
            print("  Row 1:", [td.text.strip() for td in rows[1].find_all(['td', 'th'])])


if __name__ == "__main__":
    extract_yazhi()
