import sys, os
sys.path.append(os.path.abspath('.'))
from src.llm.predictor import LLMPredictor
text = """
#### 4. 🎯 最终预测
*   **竞彩不让球推荐**：**主负**。机构开出浅盘，客队必定能穿。
*   **竞彩推荐**：**让球负（-1）**。基于机构强烈的诱客意图，看好埃门主场能够守住数据。双选可补 **让平（+1）** 防客队一球小胜。
*   **比分参考**：**1:1， 1:0**
*   **信心指数**：★★★☆☆ （机构操盘意图清晰，但需警惕客队绝对实力带来的变数）
"""
details = LLMPredictor.parse_prediction_details(text)
print(details)
