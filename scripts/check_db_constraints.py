import sqlite3
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(project_root, 'data', 'football.db')

print("=== 检查数据库约束 ===")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表结构
    cursor.execute('PRAGMA table_info(match_predictions)')
    columns = cursor.fetchall()
    
    print("当前表结构:")
    for col in columns:
        print(f"  {col[1]}: {col[2]} (pk: {col[5]})")
    
    # 检查索引
    print(f"\n=== 检查索引 ===")
    cursor.execute('PRAGMA index_list(match_predictions)')
    indexes = cursor.fetchall()
    
    for idx in indexes:
        idx_name = idx[1]
        is_unique = idx[2]  # 1表示唯一索引，0表示非唯一
        print(f"索引: {idx_name}, 唯一性: {'是' if is_unique else '否'}")
        
        # 获取索引详情
        cursor.execute(f'PRAGMA index_info({idx_name})')
        idx_details = cursor.fetchall()
        for detail in idx_details:
            print(f"  列: {detail[2]}")
    
    # 检查是否有唯一约束
    print(f"\n=== 检查SQL约束 ===")
    cursor.execute("""
        SELECT sql FROM sqlite_master 
        WHERE type='table' AND name='match_predictions'
    """)
    table_sql = cursor.fetchone()[0]
    print("表创建SQL:")
    print(table_sql)
    
    conn.close()
else:
    print(f"数据库不存在: {db_path}")