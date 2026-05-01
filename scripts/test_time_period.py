import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.llm.predictor import LLMPredictor

# 测试时间段判断逻辑
print("=== 测试时间段判断逻辑 ===")

# 当前时间
current_time = datetime.now()
print(f"当前时间: {current_time}")

# 比赛时间
match_time_str = "2026-03-27 01:00:00"
match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M:%S")
print(f"比赛时间: {match_time}")

# 计算时间差
time_diff = match_time - current_time
print(f"时间差: {time_diff}")
print(f"总秒数: {time_diff.total_seconds()}")

# 计算小时数
hours_diff = time_diff.total_seconds() / 3600
print(f"小时差: {hours_diff:.2f} 小时")

# 测试时间段判断
predictor = LLMPredictor()
test_match = {"match_time": match_time_str}
period = predictor._determine_prediction_period(test_match)
print(f"判断结果: {period}")

# 验证判断逻辑
print(f"\n验证判断逻辑:")
print(f"> 24小时? {time_diff.total_seconds() > 24 * 3600}")
print(f"> 12小时? {time_diff.total_seconds() > 12 * 3600}")
print(f"预期结果: {'pre_24h' if time_diff.total_seconds() > 24 * 3600 else 'pre_12h' if time_diff.total_seconds() > 12 * 3600 else 'final'}")

# 检查数据库中的实际数据
print(f"\n=== 检查数据库中的实际数据 ===")
from src.db.database import Database

db = Database()
predictions = db.get_all_predictions_by_fixture("1205427")  # 假设这是对应的比赛ID
print(f"找到 {len(predictions)} 条预测记录")
for pred in predictions:
    print(f"时间段: {pred.prediction_period}, 创建时间: {pred.created_at}")

db.close()