import sqlite3
import os

# 数据库路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(project_root, 'data', 'football.db')

print("=== 修复数据库约束问题 ===")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. 首先检查当前的索引
        print("1. 检查当前索引:")
        cursor.execute("PRAGMA index_list('match_predictions')")
        indexes = cursor.fetchall()
        
        for idx in indexes:
            idx_name = idx[1]
            is_unique = idx[2]
            print(f"   索引: {idx_name}, 唯一性: {'是' if is_unique else '否'}")
            
            # 获取索引详情
            cursor.execute(f"PRAGMA index_info({idx_name})")
            idx_details = cursor.fetchall()
            for detail in idx_details:
                print(f"     列: {detail[2]}")
        
        # 2. 删除现有的唯一索引
        print("\n2. 删除fixture_id的唯一索引...")
        cursor.execute("DROP INDEX IF EXISTS ix_match_predictions_fixture_id")
        print("   ✅ 索引已删除")
        
        # 3. 创建新的非唯一索引
        print("\n3. 创建新的非唯一索引...")
        cursor.execute("CREATE INDEX idx_fixture_id ON match_predictions(fixture_id)")
        cursor.execute("CREATE INDEX idx_fixture_period ON match_predictions(fixture_id, prediction_period)")
        print("   ✅ 新索引已创建")
        
        # 4. 验证修复结果
        print("\n4. 验证修复结果:")
        cursor.execute("PRAGMA index_list('match_predictions')")
        new_indexes = cursor.fetchall()
        
        for idx in new_indexes:
            idx_name = idx[1]
            is_unique = idx[2]
            print(f"   索引: {idx_name}, 唯一性: {'是' if is_unique else '否'}")
        
        # 提交更改
        conn.commit()
        print("\n✅ 数据库约束修复完成！")
        
        # 5. 测试插入多条记录
        print("\n5. 测试插入多条记录:")
        
        # 找一个测试用的fixture_id
        cursor.execute("SELECT fixture_id FROM match_predictions LIMIT 1")
        test_fixture = cursor.fetchone()
        
        if test_fixture:
            test_fixture_id = test_fixture[0]
            print(f"   测试fixture_id: {test_fixture_id}")
            
            # 检查当前记录数
            cursor.execute("SELECT COUNT(*) FROM match_predictions WHERE fixture_id = ?", (test_fixture_id,))
            current_count = cursor.fetchone()[0]
            print(f"   当前记录数: {current_count}")
            
            # 尝试插入新记录
            try:
                cursor.execute("""
                    INSERT INTO match_predictions 
                    (fixture_id, match_num, league, home_team, away_team, match_time, 
                     prediction_period, prediction_text, created_at, updated_at)
                    VALUES (?, 'test123', 'test_league', 'test_home', 'test_away', 
                            datetime('now'), 'final', '测试预测内容', datetime('now'), datetime('now'))
                """, (test_fixture_id,))
                conn.commit()
                
                # 检查插入后的记录数
                cursor.execute("SELECT COUNT(*) FROM match_predictions WHERE fixture_id = ?", (test_fixture_id,))
                new_count = cursor.fetchone()[0]
                print(f"   插入后记录数: {new_count}")
                
                if new_count > current_count:
                    print("   ✅ 成功插入新记录！多时间段功能已修复")
                else:
                    print("   ❌ 插入失败")
                    
            except Exception as e:
                print(f"   ❌ 插入错误: {e}")
        
    except Exception as e:
        print(f"修复过程中出错: {e}")
        conn.rollback()
    finally:
        conn.close()
else:
    print(f"数据库不存在: {db_path}")

print("\n=== 修复完成 ===")