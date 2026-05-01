import pandas as pd
import os

xl_path = os.path.join('docs', 'foot_prediction.xlsx')
xls = pd.ExcelFile(xl_path)
for sheet in xls.sheet_names:
    df = pd.read_excel(xl_path, sheet_name=sheet)
    for col in df.columns:
        if '编码' in str(col):
            code_col = col
        if '日期' in str(col):
            date_col = col
    if 'date_col' in locals() and 'code_col' in locals():
        match_df = df[(df[code_col] == '周二006') & (df[date_col].astype(str).str.contains('2026-04-14'))]
        if not match_df.empty:
            print("Found in sheet:", sheet)
            print(match_df.to_dict('records'))
