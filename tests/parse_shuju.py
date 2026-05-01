from bs4 import BeautifulSoup

def extract_shuju():
    with open("tests/500_shuju.html", "r", encoding="utf-8") as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 查找历史交锋
    print("--- 历史交锋 ---")
    team_jiaofeng = soup.find('div', class_='team_a')
    if team_jiaofeng:
        # 这个 div 里可能有总计信息
        bottom_info = team_jiaofeng.find('div', class_='bottom_info')
        if bottom_info:
            print(bottom_info.text.strip())

    # 查找主队近期战绩
    print("\n--- 主队近期战绩 ---")
    team_a_zhanji = soup.find('div', class_='team_a', id='team_zhanji_1') # 猜测
    # 或者用更通用的方式，500 的结构一般是 <div class="nav_info"> 等
    # 我们找包含 "近10场战绩" 的文本
    
    tables = soup.find_all('table', class_='pub_table')
    for idx, t in enumerate(tables[:3]):
        print(f"\n表格 {idx+1}:")
        rows = t.find_all('tr')
        if len(rows) > 0:
            print("表头:", [th.text.strip() for th in rows[0].find_all(['th', 'td'])])
            if len(rows) > 1:
                print("数据1:", [td.text.strip() for td in rows[1].find_all('td')])

if __name__ == "__main__":
    extract_shuju()
