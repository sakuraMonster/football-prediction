#!/usr/bin/env python3
"""
微信公众号文章限流检测与优化工具（简化版）
用法：
  python limitation_detector.py --content-file "article.md"
  python limitation_detector.py --account-data "account.json"
"""
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List

class WeChatLimitationDetector:
    def __init__(self):
        self.sensitive_indicators = [
            "竞彩", "投注", "赔率", "盘口", "水位", "庄家", "澳门", "Bet365",
            "立博", "威廉", "命中率", "稳赚", "包红", "回血", "复利"
        ]
    
    def analyze_article_content(self, content: str) -> Dict:
        """分析文章内容合规性"""
        result = {
            "risk_level": "low",
            "sensitive_words": [],
            "suggestions": [],
            "compliance_score": 100
        }
        
        # 检测敏感词
        found_sensitive = []
        for word in self.sensitive_indicators:
            if word in content:
                found_sensitive.append(word)
                
        result["sensitive_words"] = found_sensitive
        
        # 评估风险等级
        if len(found_sensitive) > 5:
            result["risk_level"] = "high"
            result["compliance_score"] = max(0, 100 - len(found_sensitive) * 15)
        elif len(found_sensitive) > 2:
            result["risk_level"] = "medium" 
            result["compliance_score"] = max(50, 100 - len(found_sensitive) * 10)
        
        # 生成优化建议
        if result["risk_level"] in ["high", "medium"]:
            result["suggestions"] = self._generate_suggestions(found_sensitive)
            
        return result
    
    def _generate_suggestions(self, sensitive_words: List[str]) -> List[str]:
        """生成优化建议"""
        suggestions = []
        
        if "竞彩" in sensitive_words:
            suggestions.append("将'竞彩'替换为'赛场观察'或'赛事分析'")
            
        if "投注" in sensitive_words:
            suggestions.append("将'投注'替换为'参考'或'关注'")
            
        if "赔率" in sensitive_words:
            suggestions.append("将'赔率'替换为'数据表现'或'市场定位'")
            
        if "盘口" in sensitive_words:
            suggestions.append("将'盘口'替换为'让步定位'或'市场让步'")
            
        suggestions.extend([
            "增加技术分析内容比重",
            "添加更多合规声明",
            "使用中性化表达方式",
            "避免直接推荐和引导"
        ])
        
        return suggestions
    
    def check_account_health(self, account_data: Dict) -> Dict:
        """检查账号健康度"""
        health_score = 100
        issues = []
        
        # 检查发文频率
        if account_data.get("weekly_articles", 0) > 7:
            health_score -= 20
            issues.append("发文频率过高，建议每周不超过5篇")
            
        # 检查阅读量趋势
        recent_reads = account_data.get("recent_read_trend", [])
        if len(recent_reads) >= 5:
            avg_read = sum(recent_reads[-5:]) / 5
            if avg_read < 10:
                health_score -= 30
                issues.append("阅读量异常偏低，可能存在限流")
            elif avg_read < 50:
                health_score -= 15
                issues.append("阅读量偏低，需要优化内容")
                
        # 检查违规记录
        violations = account_data.get("violations", 0)
        if violations > 0:
            health_score -= violations * 25
            issues.append(f"存在{violations}次违规记录")
            
        return {
            "health_score": max(0, health_score),
            "health_level": self._get_health_level(health_score),
            "issues": issues,
            "recommendations": self._get_health_recommendations(health_score)
        }
    
    def _get_health_level(self, score: int) -> str:
        if score >= 80:
            return "优秀"
        elif score >= 60:
            return "良好"
        elif score >= 40:
            return "一般"
        else:
            return "较差"
    
    def _get_health_recommendations(self, score: int) -> List[str]:
        if score >= 80:
            return ["保持当前运营策略"]
        elif score >= 60:
            return [
                "适当增加互动和用户 engagement",
                "优化内容质量和发布时间"
            ]
        elif score >= 40:
            return [
                "降低发文频率，专注内容质量",
                "检查并优化敏感内容",
                "增加合规声明和免责声明"
            ]
        else:
            return [
                "暂停发文，进行账号冷处理",
                "全面检查历史内容合规性",
                "考虑重新注册新账号",
                "联系客服申诉和咨询"
            ]

def main():
    parser = argparse.ArgumentParser(description="微信公众号限流检测与优化工具")
    parser.add_argument("--content-file", type=str, help="文章内容文件路径")
    parser.add_argument("--account-data", type=str, help="账号数据JSON文件")
    
    args = parser.parse_args()
    
    detector = WeChatLimitationDetector()
    
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
        analysis = detector.analyze_article_content(content)
        print("=== 文章内容合规性分析 ===")
        print(json.dumps(analysis, ensure_ascii=False, indent=2))
    
    if args.account_data:
        account_info = json.loads(Path(args.account_data).read_text(encoding="utf-8"))
        health = detector.check_account_health(account_info)
        print("\n=== 账号健康度评估 ===")
        print(json.dumps(health, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()