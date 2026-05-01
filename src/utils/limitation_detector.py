#!/usr/bin/env python3
"""
微信公众号文章限流检测与优化工具
用法：
  python limitation_detector.py --article-url "文章链接"
  python limitation_detector.py --check-account "公众号名称"
  python limitation_detector.py --analyze-content article.md
"""
import requests
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timedelta

class WeChatLimitationDetector:
    def __init__(self):
        self.sensitive_indicators = [
            "竞彩", "投注", "赔率", "盘口", "水位", "庄家", "澳门", "Bet365",
            "立博", "威廉", "命中率", "稳赚", "包红", "回血", "复利"
        ]
        
        self.compliance_templates = {
            "technical_analysis": [
                "战术分析", "技术统计", "数据对比", "实力评估",
                "历史交锋", "近期状态", "主客场表现"
            ],
            "neutral_expressions": {
                "竞彩推荐": "赛场观察",
                "投注建议": "参考方向", 
                "赔率分析": "数据表现",
                "盘口解读": "让步定位",
                "水位变化": "赔付区间"
            }
        }
    
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
    
    def generate_optimization_plan(self, content_analysis: Dict, account_health: Dict) -> Dict:
        """生成综合优化方案"""
        
        immediate_actions = []
        short_term_actions = []
        long_term_actions = []
        
        # 立即执行（24小时内）
        if content_analysis["risk_level"] in ["high", "medium"]:
            immediate_actions.extend([
                "暂停发布当前文章内容",
                "使用敏感词过滤器重新处理",
                "增加合规声明和免责声明"
            ])
            
        if account_health["health_score"] < 40:
            immediate_actions.extend([
                "暂停所有新内容发布",
                "检查最近10篇文章",
                "清理可能违规的评论"
            ])
        
        # 短期优化（1-2周）
        short_term_actions.extend([
            "调整发文频率至每周3-4篇",
            "增加技术分析内容比重",
            "使用更中性的表达方式",
            "主动与用户正向互动"
        ])
        
        # 长期策略（1个月+）
        long_term_actions.extend([
            "建立完整的内容审核流程",
            "培养账号专业技术形象",
            "拓展多元化内容形式",
            "建设私域流量池"
        ])
        
        return {
            "immediate": immediate_actions,
            "short_term": short_term_actions,
            "long_term": long_term_actions,
            "expected_timeline": {
                "immediate": "24小时内",
                "short_term": "1-2周",
                "long_term": "1个月+"
            }
        }
    
    def create_monitoring_dashboard(self) -> Dict:
        """创建监控面板配置"""
        return {
            "daily_metrics": [
                "文章阅读量",
                "推荐流量占比", 
                "搜索可见性",
                "用户互动率"
            ],
            "weekly_metrics": [
                "账号健康度评分",
                "内容合规率",
                "粉丝增长情况",
                "违规举报次数"
            ],
            "alert_thresholds": {
                "read_count": 10,          # 阅读量低于10预警
                "recommend_ratio": 0.1,    # 推荐流量占比低于10%预警
                "engagement_rate": 0.03,   # 互动率低于3%预警
                "health_score": 40         # 健康度低于40预警
            }
        }

def main():
    parser = argparse.ArgumentParser(description="微信公众号限流检测与优化工具")
    parser.add_argument("--content-file", type=str, help="文章内容文件路径")
    parser.add_argument("--account-data", type=str, help="账号数据JSON文件")
    parser.add_argument("--generate-report", action="store_true", help="生成完整报告")
    
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
    
    if args.generate_report:
        # 生成完整优化报告
        report = {
            "generated_at": datetime.now().isoformat(),
            "detection_methods": detector.create_monitoring_dashboard(),
            "best_practices": [
                "坚持原创内容，避免复制粘贴",
                "使用中性化表达，避免敏感词汇",
                "定期监控数据指标，及时调整策略",
                "建立多元化内容矩阵，降低单一风险",
                "重视用户互动，提升账号活跃度"
            ]
        }
        
        print("\n=== 完整优化报告 ===")
        print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()