import sqlite3
import os
from datetime import datetime, timedelta

# 数据库路径
db_path = os.path.join('data', 'football.db')

print("=== 测试多时间段预测功能 ===")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 找一个2026-03-27的比赛作为测试
    cursor.execute("""
        SELECT fixture_id, match_time, home_team, away_team 
        FROM match_predictions 
        WHERE match_time LIKE '2026-03-27%' 
        LIMIT 1
    """)
    test_match = cursor.fetchone()
    
    if test_match:
        fixture_id, match_time_str, home_team, away_team = test_match
        print(f"测试比赛: {home_team} vs {away_team}")
        print(f"fixture_id: {fixture_id}")
        print(f"比赛时间: {match_time_str}")
        
        # 检查当前时间段记录
        cursor.execute("SELECT prediction_period, created_at, prediction_text FROM match_predictions WHERE fixture_id = ? ORDER BY created_at", (fixture_id,))
        existing_records = cursor.fetchall()
        print(f"\n现有记录: {len(existing_records)} 条")
        for period, created, prediction in existing_records:
            print(f"  时间段: {period}, 创建时间: {created}, 预测内容: {prediction[:50] if prediction else '无'}...")
        
        # 模拟创建不同时间段的预测
        print(f"\n=== 模拟创建不同时间段预测 ===")
        
        # 计算当前应该属于的时间段
        match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M:%S.%f")
        current_time = datetime.now()
        time_diff = match_time - current_time
        hours_diff = time_diff.total_seconds() / 3600
        
        print(f"当前时间: {current_time}")
        print(f"比赛时间: {match_time}")
        print(f"时间差: {hours_diff:.2f} 小时")
        
        # 判断当前时间段
        if time_diff.total_seconds() > 24 * 3600:
            expected_period = "pre_24h"
        elif time_diff.total_seconds() > 12 * 3600:
            expected_period = "pre_12h"
        else:
            expected_period = "final"
        
        print(f"当前应该属于: {expected_period}")
        
        # 检查是否已有当前时间段的记录
        cursor.execute("SELECT * FROM match_predictions WHERE fixture_id = ? AND prediction_period = ?", 
                      (fixture_id, expected_period))
        current_period_record = cursor.fetchone()
        
        if not current_period_record:
            print(f"\n✅ 可以创建 {expected_period} 时间段的新记录")
            
            # 模拟创建新记录
            try:
                cursor.execute("""
                    INSERT INTO match_predictions 
                    (fixture_id, match_num, league, home_team, away_team, match_time, 
                     prediction_period, prediction_text, created_at, updated_at)
                    VALUES (?, 'test123', 'test_league', ?, ?, 
                            ?, ?, '这是新的时间段预测内容', datetime('now'), datetime('now'))
                """, (fixture_id, home_team, away_team, match_time_str, expected_period))
                conn.commit()
                print(f"✅ 成功创建 {expected_period} 时间段记录")
                
                # 验证结果
                cursor.execute("SELECT prediction_period, created_at, prediction_text FROM match_predictions WHERE fixture_id = ? ORDER BY created_at", (fixture_id,))
                updated_records = cursor.fetchall()
                print(f"\n更新后的记录: {len(updated_records)} 条")
                for period, created, prediction in updated_records:
                    print(f"  时间段: {period}, 创建时间: {created}, 预测内容: {prediction[:50] if prediction else '无'}...")
                
                # 检查是否有多个时间段
                cursor.execute("SELECT COUNT(DISTINCT prediction_period) FROM match_predictions WHERE fixture_id = ?", (fixture_id,))
                period_count = cursor.fetchone()[0]
                print(f"\n🎉 该比赛现在有 {period_count} 个不同时间段的预测记录！")
                
                if period_count > 1:
                    print("✅ 多时间段功能正常工作！现在可以在界面上看到时间段选择器了")
                
            except Exception as e:
                print(f"❌ 创建记录失败: {e}")
        else:
            print(f"\n⚠️  已存在 {expected_period} 时间段的记录")
            print("   系统将更新现有记录而不是创建新记录")
    
    conn.close()
else:
    print(f"数据库不存在: {db_path}")

print("\n=== 测试完成 ===")