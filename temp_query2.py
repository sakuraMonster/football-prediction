import pandas as pd
import os

xl_path = os.path.join('docs', 'foot_prediction.xlsx')
xls = pd.ExcelFile(xl_path)
for sheet in xls.sheet_names:
    if '2026-04-14' in sheet:
        df = pd.read_excel(xl_path, sheet_name=sheet)
        for col in df.columns:
            if '编码' in str(col):
                code_col = col
            if '进球盘口' in str(col):
                pan_col = col
            if '预测差异百分比' in str(col):
                diff_col = col
            if '倾向' in str(col):
                trend_col = col
        match_df = df[df[code_col] == '周二006']
        if not match_df.empty:
            print(match_df[[code_col, pan_col, diff_col, trend_col]].to_dict('records'))
