"""
欧赔初赔→临赔变化 vs 赛果 规律挖掘分析脚本
从 euro_odds_history 表读取数据，按赔率比×降幅×资金方向三维交叉分析，
自动找出"热钱反向/共识过载/实力碾压"的精确阈值。

输出: 控制台报告 + data/reports/euro_odds_pattern_analysis.json
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict
from datetime import datetime
import json

from src.db.database import Database
from sqlalchemy import text


class EuroOddsAnalyzer:
    """欧赔变化规律分析器"""

    # 赔率比分档
    RATIO_BINS = [
        (1.00, 1.15, "非常接近(<1.15)"),
        (1.15, 1.25, "一方稍优(1.15-1.25)"),
        (1.25, 1.40, "明显优势(1.25-1.40)"),
        (1.40, 2.00, "实力碾压(1.40-2.0)"),
        (2.00, 99.0, "绝对碾压(>2.0)"),
    ]

    # 降幅分档（热门方赔率变化率）
    DROP_BINS = [
        (0.00, 0.05, "微降<5%"),
        (0.05, 0.10, "小降5-10%"),
        (0.10, 0.20, "中降10-20%"),
        (0.20, 0.99, "骤降>20%"),
    ]

    # 资金方向
    FLOW_TYPES = {
        "consensus": "共识同向(钱追强队)",
        "contrarian": "反向背离(钱追弱队)",
    }

    def __init__(self):
        self.db = Database()

    def load_data(self):
        """从数据库加载数据，按 fixture_id 聚合"""
        sql = """
        SELECT fixture_id, league, home_team, away_team, company,
               init_home, init_draw, init_away,
               live_home, live_draw, live_away,
               actual_result
        FROM euro_odds_history
        WHERE actual_result IS NOT NULL AND actual_result != ''
        ORDER BY fixture_id, company
        """
        rows = self.db.session.execute(text(sql)).fetchall()

        # 按 fixture_id 聚合
        fixtures = defaultdict(list)
        for row in rows:
            fixtures[row[0]].append({
                "league": row[1],
                "home_team": row[2],
                "away_team": row[3],
                "company": row[4],
                "init_home": float(row[5]),
                "init_draw": float(row[6]),
                "init_away": float(row[7]),
                "live_home": float(row[8]),
                "live_draw": float(row[9]),
                "live_away": float(row[10]),
                "actual_result": row[11],
            })

        print(f"加载 {len(fixtures)} 个 fixture_id 的欧赔数据")
        return fixtures

    def safe_float(self, v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def classify_ratio(self, ratio):
        """将赔率比分类到对应档位"""
        for lo, hi, label in self.RATIO_BINS:
            if lo <= ratio < hi:
                return label
        return self.RATIO_BINS[-1][2]

    def classify_drop(self, drop_pct):
        """将降幅分类到对应档位"""
        for lo, hi, label in self.DROP_BINS:
            if lo <= abs(drop_pct) < hi:
                return label
        return self.DROP_BINS[-1][2]

    def analyze_match(self, match_rows):
        """
        对单场比赛的5家公司数据做分析。
        使用 澳门(*门) 为主参考，若无比对则取竞彩官方(竞*官*)。
        """
        # 确定主参考公司：澳门 > 竞彩官方 > 第一条
        ref_row = None
        for row in match_rows:
            if "门" in row["company"] and "中国澳门" in row["company"]:
                ref_row = row
                break
        if not ref_row:
            for row in match_rows:
                if "竞" in row["company"]:
                    ref_row = row
                    break
        if not ref_row:
            ref_row = match_rows[0]

        ih = ref_row["init_home"]
        ia = ref_row["init_away"]
        lh = ref_row["live_home"]
        la = ref_row["live_away"]
        result = ref_row["actual_result"]

        if ih <= 0 or ia <= 0 or lh <= 0 or la <= 0:
            return None

        # 赔率比（高赔/低赔）
        init_max = max(ih, ia)
        init_min = min(ih, ia)
        ratio = init_max / init_min

        # 初始实力指向：初赔低的一方为强队
        init_stronger = "home" if ih < ia else "away"
        if ih == ia:
            init_stronger = "equal"

        # 资金方向判定：哪边赔率下降了（降幅更大的方向 = 资金流入方向）
        home_change_pct = (lh - ih) / ih  # 正=升水(被抛售), 负=降(被买入)
        away_change_pct = (la - ia) / ia

        # 资金流入方 = 赔率降幅更大的一方
        if home_change_pct < away_change_pct:
            money_flow_to = "home"
            drop_pct = abs(home_change_pct)
        else:
            money_flow_to = "away"
            drop_pct = abs(away_change_pct)

        # 方向判定
        if init_stronger == "equal":
            flow_dir = "equal_initial"
        elif money_flow_to == init_stronger:
            flow_dir = "consensus"  # 共识同向：钱追强队
        else:
            flow_dir = "contrarian"  # 反向背离：钱追弱队

        # 实际赛果中，资金流入方是否打出
        money_flow_home_win = (money_flow_to == "home" and result == "胜")
        money_flow_away_win = (money_flow_to == "away" and result == "负")
        money_flow_draw = (result == "平")
        money_side_won = money_flow_home_win or money_flow_away_win

        # 初始强队是否打出
        stronger_home_win = (init_stronger == "home" and result == "胜")
        stronger_away_win = (init_stronger == "away" and result == "负")
        stronger_won = stronger_home_win or stronger_away_win

        return {
            "league": ref_row["league"],
            "home_team": ref_row["home_team"],
            "away_team": ref_row["away_team"],
            "init_home": ih,
            "init_away": ia,
            "live_home": lh,
            "live_away": la,
            "ratio": round(ratio, 3),
            "ratio_label": self.classify_ratio(ratio),
            "init_stronger": init_stronger,
            "money_flow_to": money_flow_to,
            "drop_pct": round(drop_pct, 4),
            "drop_label": self.classify_drop(drop_pct),
            "home_change_pct": round(home_change_pct, 4),
            "away_change_pct": round(away_change_pct, 4),
            "flow_dir": flow_dir,
            "result": result,
            "money_side_won": money_side_won,
            "stronger_won": stronger_won,
            "money_flow_home_win": money_flow_home_win,
            "money_flow_away_win": money_flow_away_win,
            "money_flow_draw": money_flow_draw,
        }

    def run(self):
        fixtures = self.load_data()

        # 分析每场比赛
        analyzed = []
        for fid, rows in fixtures.items():
            info = self.analyze_match(rows)
            if info:
                analyzed.append(info)

        print(f"\n成功分析 {len(analyzed)} 场比赛\n")
        print("=" * 80)

        # ============================================================
        # 报告1: 全维度交叉分析
        # ============================================================
        print("\n## 一、三维交叉分析：赔率比 × 降幅 × 资金方向\n")

        cross_table = defaultdict(lambda: {"total": 0, "money_won": 0, "stronger_won": 0})

        for m in analyzed:
            key = (m["ratio_label"], m["drop_label"], m["flow_dir"])
            cross_table[key]["total"] += 1
            if m["money_side_won"]:
                cross_table[key]["money_won"] += 1
            if m["stronger_won"]:
                cross_table[key]["stronger_won"] += 1

        # 按赔率比分组打印
        for ratio_label, _, _ in self.RATIO_BINS:
            has_data = any(k[0] == ratio_label for k in cross_table)
            if not has_data:
                continue

            print(f"\n### {ratio_label}")
            print(f"{'资金方向':<20} {'降幅区间':<18} {'样本':>5} {'资金方打出':>10} {'命中率':>8} {'强队打出':>10} {'强队率':>8}")
            print("-" * 90)

            for flow_key, flow_name in self.FLOW_TYPES.items():
                for _, drop_label, _ in self.DROP_BINS:
                    key = (ratio_label, drop_label, flow_key)
                    if key not in cross_table:
                        continue
                    d = cross_table[key]
                    money_rate = d["money_won"] / d["total"] * 100 if d["total"] else 0
                    stronger_rate = d["stronger_won"] / d["total"] * 100 if d["total"] else 0
                    flag = ""
                    if d["total"] >= 5:
                        if flow_key == "contrarian" and money_rate < 35:
                            flag = " 🔴 诱盘陷阱!"
                        elif flow_key == "consensus" and ratio_label.startswith("非常接近") and drop_pct_value(drop_label) > 0.10 and money_rate < 40:
                            flag = " 🔴 共识过载!"
                        elif flow_key == "consensus" and (ratio_label.startswith("实力碾压") or ratio_label.startswith("绝对碾压")) and money_rate > 60:
                            flag = " 🟢 实力型热度"

                    print(f"{flow_name:<20} {drop_label:<18} {d['total']:>5} {d['money_won']:>7}/{d['total']:<5} {money_rate:>6.1f}% {d['stronger_won']:>7}/{d['total']:<5} {stronger_rate:>6.1f}%{flag}")

        # ============================================================
        # 报告2: 简版总结
        # ============================================================
        print("\n\n## 二、关键发现总结\n")

        # 发现1: 反向背离 + 明显差距以上 → 诱盘陷阱
        findings = []

        for key, d in cross_table.items():
            ratio_label, drop_label, flow_dir = key
            if d["total"] < 5:
                continue
            money_rate = d["money_won"] / d["total"] * 100

            if flow_dir == "contrarian" and money_rate < 40:
                findings.append({
                    "type": "诱盘陷阱",
                    "condition": f"{ratio_label} + {drop_label} + 反向背离",
                    "samples": d["total"],
                    "money_side_win_rate": round(money_rate, 1),
                    "conclusion": "钱追弱队但弱队胜率极低 → 机构设陷阱收割追弱队的资金 → 强队正常打出",
                })

            if flow_dir == "consensus" and "接近" in ratio_label and drop_pct_value(drop_label) > 0.10 and money_rate < 45:
                findings.append({
                    "type": "共识过载",
                    "condition": f"{ratio_label} + {drop_label} + 共识同向",
                    "samples": d["total"],
                    "money_side_win_rate": round(money_rate, 1),
                    "conclusion": "实力接近时狂热追捧一方 → 该方危险 → 冷门方不败",
                })

        findings.sort(key=lambda x: x["money_side_win_rate"])
        for i, f in enumerate(findings[:8]):
            print(f"{i+1}. [{f['type']}] {f['condition']}")
            print(f"   样本={f['samples']}场, 资金方胜率={f['money_side_win_rate']}%")
            print(f"   → {f['conclusion']}")
            print()

        # ============================================================
        # 报告3: 总体统计
        # ============================================================
        print("\n## 三、总体基准统计\n")
        total = len(analyzed)
        strong_wins = sum(1 for m in analyzed if m["stronger_won"])
        money_wins = sum(1 for m in analyzed if m["money_side_won"])

        print(f"总样本: {total} 场")
        print(f"初赔强队打出率: {strong_wins}/{total} = {strong_wins/total*100:.1f}%")
        print(f"资金流入方打出率: {money_wins}/{total} = {money_wins/total*100:.1f}%")

        # 按方向统计
        consensus_matches = [m for m in analyzed if m["flow_dir"] == "consensus"]
        contrarian_matches = [m for m in analyzed if m["flow_dir"] == "contrarian"]
        consensus_wins = sum(1 for m in consensus_matches if m["money_side_won"])
        contrarian_wins = sum(1 for m in contrarian_matches if m["money_side_won"])

        print(f"\n共识同向(追强队): {len(consensus_matches)}场, 资金方打出 {consensus_wins}场 ({consensus_wins/len(consensus_matches)*100:.1f}%)" if consensus_matches else "")
        print(f"反向背离(追弱队): {len(contrarian_matches)}场, 资金方打出 {contrarian_wins}场 ({contrarian_wins/len(contrarian_matches)*100:.1f}%)" if contrarian_matches else "")

        # ============================================================
        # 导出JSON
        # ============================================================
        output = {
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_samples": total,
            "overall_money_side_win_rate": round(money_wins / total * 100, 1) if total else 0,
            "overall_stronger_win_rate": round(strong_wins / total * 100, 1) if total else 0,
            "findings": findings,
            "cross_table": {str(k): v for k, v in cross_table.items()},
        }

        os.makedirs("data/reports", exist_ok=True)
        with open("data/reports/euro_odds_pattern_analysis.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n\n详细数据已导出到: data/reports/euro_odds_pattern_analysis.json")

        self.db.close()
        return analyzed, findings


def drop_pct_value(label):
    """从降幅标签提取上限"""
    if ">20%" in label:
        return 0.25
    if "10-20%" in label:
        return 0.15
    if "5-10%" in label:
        return 0.08
    return 0.03


if __name__ == "__main__":
    analyzer = EuroOddsAnalyzer()
    analyzer.run()
