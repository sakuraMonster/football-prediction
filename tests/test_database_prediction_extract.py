from src.db.database import Database


def test_extract_prediction_recommendation_dual():
    text = """
- **🎯 最终预测**：
   - **竞彩推荐**：平(50%)/负(50%)
   - **竞彩让球推荐**：让平(50%)/让负(50%)
"""
    assert Database.extract_prediction_recommendation(text) == "平(50%)/负(50%)"


def test_extract_prediction_recommendation_single():
    text = """
**🎯 最终预测**：
- **竞彩推荐**：胜 (100%)
- **竞彩让球推荐**：让平(55%) / 让负(45%)
"""
    assert Database.extract_prediction_recommendation(text) == "胜 (100%)"


def test_extract_prediction_recommendation_none():
    assert Database.extract_prediction_recommendation("无有效推荐") is None
