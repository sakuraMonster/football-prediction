import pandas as pd
import sqlite3

xl_path = 'docs/foot_prediction.xlsx'
xl = pd.ExcelFile(xl_path)
dfs = []
for sheet in xl.sheet_names:
    if sheet.startswith('2025') or sheet.startswith('2026'):
        df = pd.read_excel(xl, sheet_name=sheet)
        dfs.append(df)
        print(f'Sheet {sheet}: {len(df)} rows')

df_excel = pd.concat(dfs, ignore_index=True)
df_excel.columns = df_excel.columns.str.strip()
df_excel = df_excel.dropna(subset=['编码'])
print(f'\nTotal rows after dropping empty codes: {len(df_excel)}')

df_excel['日期'] = pd.to_datetime(df_excel['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
unique_dates = df_excel['日期'].dropna().unique().tolist()
dates_str = ', '.join([f"'{d}'" for d in unique_dates])

db_path = 'data/football.db'
conn = sqlite3.connect(db_path)
query = f"""
SELECT match_num as 编码, league, match_time, created_at
FROM match_predictions
WHERE date(match_time) IN ({dates_str}) OR date(created_at) IN ({dates_str})
"""
df_db = pd.read_sql(query, conn)

def get_league(row):
    code = row['编码']
    date_val = row['日期']
    matches = df_db[df_db['编码'] == code]
    if not matches.empty:
        return matches.iloc[0]['league']
    return None

df_excel['league'] = df_excel.apply(get_league, axis=1)

merged = df_excel.copy()
merged['倾向'] = merged['倾向'].astype(str).str.strip()
merged['进球数'] = pd.to_numeric(merged['进球数'], errors='coerce')
merged['预测差异百分比'] = pd.to_numeric(merged['预测差异百分比'], errors='coerce')
merged['进球盘口'] = merged['进球盘口'].astype(str).str.strip()

missing_league = merged['league'].isna().sum()
missing_pan = merged['进球盘口'].replace('nan', pd.NA).isna().sum()
missing_diff = merged['预测差异百分比'].isna().sum()
missing_trend = merged['倾向'].replace('nan', pd.NA).isna().sum()
missing_goals = merged['进球数'].isna().sum()

print(f'\nMissing League (not found in DB): {missing_league}')
print(f'Missing Pan: {missing_pan}')
print(f'Missing Diff: {missing_diff}')
print(f'Missing Trend: {missing_trend}')
print(f'Missing Actual Goals: {missing_goals}')

valid_data = merged.dropna(subset=['league', '进球盘口', '预测差异百分比', '倾向', '进球数']).copy()
print(f'\nFinal Valid Data rows used for report: {len(valid_data)}')

# Print details for 04-14
df_14 = merged[merged['日期'] == '2026-04-14']
print(f'\nDetails for 2026-04-14 (Total {len(df_14)} rows):')
for _, row in df_14.iterrows():
    is_valid = not pd.isna(row['league']) and not pd.isna(row['预测差异百分比']) and not pd.isna(row['进球数'])
    print(f"{row['编码']} - League:{row['league']}, Goals:{row['进球数']}, Diff:{row['预测差异百分比']} -> Valid: {is_valid}")
