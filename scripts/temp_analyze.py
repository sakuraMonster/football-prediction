import pandas as pd
import sqlite3
import os

def analyze():
    print("Starting analysis...")
    # 1. Read Excel
    xl_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'foot_prediction.xlsx')
    if not os.path.exists(xl_path):
        xl_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', '新建 XLSX 工作表.xlsx')
    
    xl = pd.ExcelFile(xl_path)
    dfs = []
    for sheet in xl.sheet_names:
        if sheet.startswith('2025') or sheet.startswith('2026'):
            df = pd.read_excel(xl, sheet_name=sheet)
            dfs.append(df)
    df_excel = pd.concat(dfs, ignore_index=True)

    # Rename columns to remove leading/trailing spaces
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.dropna(subset=['编码'])

    # 2. Read DB
    db_path = 'data/football.db'
    conn = sqlite3.connect(db_path)
    
    # 提取 Excel 中所有的日期，作为查询数据库的过滤条件
    df_excel['日期'] = pd.to_datetime(df_excel['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
    
    # Check what we already have in the persistent history table
    try:
        import pandas.io.sql as sql_io
        history_df = pd.read_sql("SELECT * FROM goal_analysis_history", conn)
        print(f"Loaded {len(history_df)} historical matches from database.")
    except Exception as e:
        # Table doesn't exist yet
        history_df = pd.DataFrame()
        print("No historical analysis table found. It will be created.")

    # Create a unique match identifier (Date + Code) to prevent duplicates in current excel parsing
    df_excel['unique_id'] = df_excel['日期'].astype(str) + '_' + df_excel['编码'].astype(str)
    
    # If we have historical data, filter out matches we've already processed completely
    if not history_df.empty:
        # We only want to process matches that are NOT in history_df, 
        # OR matches in history_df where the actual_goals might have been missing/updated
        # For simplicity and safety, we will just parse everything from Excel, 
        # deduplicate, and then the INSERT OR REPLACE will handle updates.
        pass

    unique_dates = df_excel['日期'].dropna().unique().tolist()
    dates_str = ', '.join([f"'{d}'" for d in unique_dates])
    
    query = f"""
    SELECT match_num as 编码, league, home_team, away_team, match_time, created_at
    FROM match_predictions
    WHERE date(match_time) IN ({dates_str}) OR date(created_at) IN ({dates_str})
    """
    df_db = pd.read_sql(query, conn)
    
    def get_match_info(row):
        code = row['编码']
        date_val = row['日期']
        matches = df_db[df_db['编码'] == code]
        for _, m in matches.iterrows():
            m_time = str(m['match_time'])[:10] if pd.notna(m['match_time']) else ""
            c_time = str(m['created_at'])[:10] if pd.notna(m['created_at']) else ""
            if m_time == date_val or c_time == date_val:
                return pd.Series([m['league'], m['home_team'], m['away_team']])
        if not matches.empty:
            m = matches.iloc[0]
            return pd.Series([m['league'], m['home_team'], m['away_team']])
        return pd.Series([None, None, None])

    df_excel[['league', 'home_team', 'away_team']] = df_excel.apply(get_match_info, axis=1)

    # 3. Merge
    merged = df_excel.copy()

    # Clean data
    merged['倾向'] = merged['倾向'].astype(str).str.strip()
    merged['进球数'] = pd.to_numeric(merged['进球数'], errors='coerce')
    merged['预测差异百分比'] = pd.to_numeric(merged['预测差异百分比'], errors='coerce')
    merged['进球盘口'] = merged['进球盘口'].astype(str).str.strip()

    # Create a unique match identifier (Date + Code) to prevent duplicates
    merged['unique_id'] = merged['日期'].astype(str) + '_' + merged['编码'].astype(str)
    # Drop duplicate matches keeping the first occurrence
    initial_rows = len(merged)
    merged = merged.drop_duplicates(subset=['unique_id'], keep='first')
    dedup_rows = len(merged)
    if initial_rows > dedup_rows:
        print(f"Removed {initial_rows - dedup_rows} duplicate matches based on Date+Code.")

    # Drop rows with NaN in critical columns (不需要检查 预测进球数，因为历史复盘只需要实际进球数)
    valid_data = merged.dropna(subset=['league', '进球盘口', '预测差异百分比', '倾向', '进球数']).copy()
    valid_data['进球数'] = valid_data['进球数'].astype(int)

    # 4. Define League Clusters
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.llm.goals_predictor import GoalsPredictor
    
    predictor = GoalsPredictor()
    llm_cluster_cache = {}

    def assign_cluster(row):
        league = str(row['league'])
        home_team = str(row['home_team'])
        away_team = str(row['away_team'])
        
        special_leagues = ['欧冠', '欧联', '欧罗巴', '欧协联', '欧国联', '世预赛', '欧洲杯', '亚洲杯', '美洲杯', '俱乐部杯', '亚冠', '亚洲']
        is_special = any(sl in league for sl in special_leagues)
        
        if is_special and home_team and away_team and home_team != 'None' and away_team != 'None':
            cache_key = f"{home_team}_{away_team}"
            if cache_key in llm_cluster_cache:
                return llm_cluster_cache[cache_key]
            cluster = predictor._determine_cluster_with_llm(home_team, away_team)
            llm_cluster_cache[cache_key] = cluster
            return cluster
            
        # A组：开放大开大合型（高波动、防守差）
        group_a = ['澳超', '挪超', '荷甲', '荷乙', '瑞超', '美职足', '沙特职业联赛', '芬兰超级联赛']
        # B组：严密防守型（强战术、老龄化或小比分基因）
        group_b = ['意甲', '西乙', '法乙', '阿甲', '葡超', '英冠', '解放者杯', '南美杯']
        # C组：主流均衡型（实力鸿沟大、战术丰富）
        group_c = ['英超', '德甲', '西甲', '法甲', '德乙']
        # D组：日韩孤立型（独立体系，战意受盘外因素影响大）
        group_d = ['日职', '韩职', '韩K']
        
        for g in group_a:
            if g in league: return 'A组：开放大开大合型'
        for g in group_b:
            if g in league: return 'B组：严密防守型'
        for g in group_c:
            if g in league: return 'C组：主流均衡型'
        for g in group_d:
            if g in league: return 'D组：日韩孤立型'
            
        return 'E组：其他未分类联赛'

    valid_data['cluster'] = valid_data.apply(assign_cluster, axis=1)

    # 5. Save to database for persistence and avoiding future duplicates
    try:
        # Create table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_analysis_history (
                unique_id TEXT PRIMARY KEY,
                match_date TEXT,
                match_code TEXT,
                league TEXT,
                pan TEXT,
                diff REAL,
                trend TEXT,
                actual_goals INTEGER,
                cluster TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert new valid records into the database
        records_to_insert = []
        for _, row in valid_data.iterrows():
            records_to_insert.append((
                row['unique_id'],
                row['日期'],
                row['编码'],
                row['league'],
                row['进球盘口'],
                row['预测差异百分比'],
                row['倾向'],
                row['进球数'],
                row['cluster']
            ))
            
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO goal_analysis_history 
            (unique_id, match_date, match_code, league, pan, diff, trend, actual_goals, cluster)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records_to_insert)
        conn.commit()
        print(f"Persisted {len(records_to_insert)} analyzed matches to database table 'goal_analysis_history'.")
        
        # Now, load ALL historical data from the DB to build the final report
        # This ensures we don't lose data even if someone deletes old sheets from Excel
        all_historical_data = pd.read_sql("SELECT * FROM goal_analysis_history", conn)
        print(f"Total historical matches available for report: {len(all_historical_data)}")
        
        # Map DB column names back to what the report generator expects
        valid_data = all_historical_data.rename(columns={
            'match_date': '日期',
            'match_code': '编码',
            'pan': '进球盘口',
            'diff': '预测差异百分比',
            'trend': '倾向',
            'actual_goals': '进球数'
        })
        
    except Exception as e:
        print(f"Warning: Failed to persist to database: {e}")
    finally:
        conn.close()

    # 6. Analyze & Generate Report
    report = ["# 进球数概率分布统计报告 (基于进球盘口、预测差异百分比、倾向及联赛特征聚类)\n"]
    report.append("本报告基于 Excel 数据与数据库赛事的匹配，按**联赛特征聚类**统计了不同条件下实际进球数的概率分布，旨在为大模型提供后验概率依据。\n")
    
    # 统计总体情况
    report.append(f"**有效统计场次**: {len(valid_data)} 场\n")
    
    # 按聚类分组统计
    clusters = valid_data['cluster'].unique()
    
    for cluster in sorted(clusters):
        cluster_data = valid_data[valid_data['cluster'] == cluster]
        report.append(f"## 联赛特征组: {cluster} (共 {len(cluster_data)} 场)")
        
        # 列出该组包含的具体联赛
        leagues_in_cluster = cluster_data['league'].unique()
        report.append(f"**包含联赛**: {', '.join(leagues_in_cluster)}\n")
        
        # 按照 进球盘口, 差异百分比, 倾向 分组
        grouped = cluster_data.groupby(['进球盘口', '预测差异百分比', '倾向'])
        
        for name, group in grouped:
            pan, diff, trend = name
            total_matches = len(group)
            
            # 计算进球数分布
            goal_counts = group['进球数'].value_counts().sort_index()
            
            diff_str = f"{diff*100:.0f}%" if diff <= 1 else f"{diff:.0f}%"
            
            report.append(f"### 盘口: `{pan}` | 预测差异: `{diff_str}` | 倾向: `{trend}` (样本: {total_matches}场)")
            report.append("| 实际进球数 | 出现次数 | 概率分布 |")
            report.append("| :--- | :--- | :--- |")
            
            for goals, count in goal_counts.items():
                prob = (count / total_matches) * 100
                report.append(f"| {goals} 球 | {count} 场 | {prob:.1f}% |")
            report.append("\n")

    # Write to markdown file
    out_path = 'docs/goal_distribution_analysis.md'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report))
    
    print(f"Analysis complete. Report saved to {out_path}")

if __name__ == '__main__':
    analyze()
