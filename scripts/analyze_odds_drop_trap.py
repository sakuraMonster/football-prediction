import sqlite3
import pandas as pd

def analyze_odds_drop_trap(db_path='data/football.db'):
    conn = sqlite3.connect(db_path)
    
    query = """
    SELECT 
        actual_result,
        CAST(init_home AS REAL) as ih, CAST(live_home AS REAL) as lh,
        CAST(init_away AS REAL) as ia, CAST(live_away AS REAL) as la,
        company
    FROM euro_odds_history
    WHERE actual_result IN ('胜', '平', '负')
      AND CAST(init_home AS REAL) > 0 AND CAST(live_home AS REAL) > 0 
      AND CAST(init_away AS REAL) > 0 AND CAST(live_away AS REAL) > 0
      AND (company LIKE '%门%' OR company LIKE '%3*5%')
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print("没有查询到足够的数据。")
        return
        
    print(f"总计提取到 {len(df)} 条澳门/Bet365的有效欧赔历史数据。")
    
    # 计算降幅百分比 (正数表示下降)
    df['home_drop_pct'] = (df['ih'] - df['lh']) / df['ih'] * 100
    df['away_drop_pct'] = (df['ia'] - df['la']) / df['ia'] * 100
    
    # 分析主队赔率下降情况
    print("\n--- 主胜赔率下降（大热）陷阱分析 ---")
    print("条件：主胜赔率下降X%，但最终没有打出主胜（即打出平/负，诱导成功）")
    
    bins = [0, 1, 2, 3, 4, 5, 10, 100]
    labels = ['0-1%', '1-2%', '2-3%', '3-4%', '4-5%', '5-10%', '>10%']
    
    home_drops = df[df['home_drop_pct'] > 0].copy()
    home_drops['drop_bin'] = pd.cut(home_drops['home_drop_pct'], bins=bins, labels=labels, right=False)
    
    home_stats = []
    for bin_label in labels:
        bin_data = home_drops[home_drops['drop_bin'] == bin_label]
        total = len(bin_data)
        if total == 0:
            continue
        # 陷阱成功：没打出主胜 (平或负)
        trap_success = len(bin_data[bin_data['actual_result'].isin(['平', '负'])])
        trap_rate = trap_success / total * 100
        home_stats.append({
            '降幅区间': bin_label,
            '样本数': total,
            '陷阱打出(未胜)': trap_success,
            '陷阱概率(不胜率)': f"{trap_rate:.1f}%"
        })
    
    print(pd.DataFrame(home_stats).to_string(index=False))

    # 分析客队赔率下降情况
    print("\n--- 客胜赔率下降（大热）陷阱分析 ---")
    print("条件：客胜赔率下降X%，但最终没有打出客胜（即打出胜/平，诱导成功）")
    
    away_drops = df[df['away_drop_pct'] > 0].copy()
    away_drops['drop_bin'] = pd.cut(away_drops['away_drop_pct'], bins=bins, labels=labels, right=False)
    
    away_stats = []
    for bin_label in labels:
        bin_data = away_drops[away_drops['drop_bin'] == bin_label]
        total = len(bin_data)
        if total == 0:
            continue
        # 陷阱成功：没打出客胜 (胜或平)
        trap_success = len(bin_data[bin_data['actual_result'].isin(['胜', '平'])])
        trap_rate = trap_success / total * 100
        away_stats.append({
            '降幅区间': bin_label,
            '样本数': total,
            '陷阱打出(未胜)': trap_success,
            '陷阱概率(不胜率)': f"{trap_rate:.1f}%"
        })
    
    print(pd.DataFrame(away_stats).to_string(index=False))

if __name__ == "__main__":
    analyze_odds_drop_trap()