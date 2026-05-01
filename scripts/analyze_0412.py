import pandas as pd
import json
import re

xl_path = 'docs/foot_prediction.xlsx'
df = pd.read_excel(xl_path, sheet_name='2026-04-12')

def clean_col(col): return str(col).strip() if pd.notna(col) else ''

df['进球数'] = pd.to_numeric(df['进球数'], errors='coerce')
pred_col = [c for c in df.columns if '重新预测' in str(c) and '命中' not in str(c)][0]
df[pred_col] = df[pred_col].apply(clean_col)

total = 0
correct = 0
wrong_matches = []

for _, row in df.iterrows():
    if pd.isna(row['进球数']) or not row[pred_col]:
        continue
        
    actual = int(row['进球数'])
    pred_str = row[pred_col]
    
    nums = re.findall(r'\d+', pred_str)
    pred_nums = [int(n) for n in nums]
    
    if not pred_nums:
        continue
        
    total += 1
    if actual in pred_nums:
        correct += 1
    else:
        wrong_matches.append({
            'code': row['编码'],
            'home': row['主队'],
            'away': row['客队'],
            'pan': str(row.get('进球盘口', '')),
            'diff': str(row.get('预测差异百分比', '')),
            'trend': str(row.get(' 倾向', row.get('倾向', ''))),
            'actual': actual,
            'pred': pred_str
        })

print(f'Total: {total}, Correct: {correct}, Accuracy: {correct/total*100:.2f}%')
print("-" * 50)
for w in wrong_matches:
    print(f"{w['code']} {w['home']} vs {w['away']} | 盘口:{w['pan']} 差异:{w['diff']} 倾向:{w['trend']} | 实际:{w['actual']} 预测:{w['pred']}")
