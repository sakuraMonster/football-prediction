import sqlite3
import os
from datetime import datetime, timedelta

# 数据库路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(project_root, 'data', 'football.db')

print("=== 调试重新预测功能 ===")

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
        
        # 检查重新预测前的记录
        cursor.execute("SELECT prediction_period, created_at FROM match_predictions WHERE fixture_id = ?", (fixture_id,))
        existing_records = cursor.fetchall()
        print(f"\n重新预测前的记录: {len(existing_records)} 条")
        for period, created in existing_records:
            print(f"  时间段: {period}, 创建时间: {created}")
        
        # 模拟重新预测过程
        print(f"\n=== 模拟重新预测过程 ===")
        
        # 1. 计算当前时间段
        match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M:%S.%f")
        current_time = datetime.now()
        time_diff = match_time - current_time
        hours_diff = time_diff.total_seconds() / 3600
        
        print(f"当前时间: {current_time}")
        print(f"比赛时间: {match_time}")
        print(f"时间差: {hours_diff:.2f} 小时")
        
        # 2. 判断当前时间段
        if time_diff.total_seconds() > 24 * 3600:
            expected_period = "pre_24h"
        elif time_diff.total_seconds() > 12 * 3600:
            expected_period = "pre_12h"
        else:
            expected_period = "final"
        
        print(f"当前应该属于: {expected_period}")
        
        # 3. 检查是否已存在当前时间段的记录
        cursor.execute("SELECT * FROM match_predictions WHERE fixture_id = ? AND prediction_period = ?", 
                      (fixture_id, expected_period))
        current_period_record = cursor.fetchone()
        
        if current_period_record:
            print(f"\n⚠️  已存在 {expected_period} 时间段的记录，将更新现有记录")
        else:
            print(f"\n✅ 不存在 {expected_period} 时间段的记录，将创建新记录")
        
        # 4. 模拟保存预测
        print(f"\n=== 模拟保存预测 ===")
        
        # 创建测试数据
        test_match_data = {
            'fixture_id': fixture_id,
            'match_num': 'test123',
            'league': 'test_league',
            'home_team': home_team,
            'away_team': away_team,
            'match_time': match_time_str,
            'llm_prediction': '测试预测内容'
        }
        
        # 检查保存逻辑
        if not current_period_record:
            print(f"执行INSERT操作: 新增 {expected_period} 时间段记录")
            cursor.execute("""
                INSERT INTO match_predictions 
                (fixture_id, match_num, league, home_team, away_team, match_time, 
                 prediction_period, prediction_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """, (fixture_id, 'test123', 'test_league', home_team, away_team, 
                  match_time_str, expected_period, '测试预测内容'))
            conn.commit()
            print("✅ 新记录创建成功")
        else:
            print(f"执行UPDATE操作: 更新现有 {expected_period} 时间段记录")
            cursor.execute("""
                UPDATE match_predictions 
                SET prediction_text = ?, updated_at = datetime('now')
                WHERE fixture_id = ? AND prediction_period = ?
            """, ('测试预测内容', fixture_id, expected_period))
            conn.commit()
            print("✅ 记录更新成功")
        
        # 5. 验证结果
        print(f"\n=== 验证结果 ===")
        cursor.execute("SELECT prediction_period, created_at, prediction_text FROM match_predictions WHERE fixture_id = ?", (fixture_id,))
        updated_records = cursor.fetchall()
        print(f"更新后的记录: {len(updated_records)} 条")
        for period, created, prediction in updated_records:
            print(f"  时间段: {period}, 创建时间: {created}, 预测内容: {prediction[:50]}...")
    
    conn.close()
else:
    print(f"数据库不存在: {db_path}")

print("\n=== 调试完成 ===")