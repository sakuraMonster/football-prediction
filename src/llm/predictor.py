import os
import re
import json
import urllib.parse
from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 引入动态规则模块
from .rules import P0_CORE_RULES, HANDICAP_RULES, DYNAMIC_CHANGE_RULES
from .rules import AGENT_A_PROMPT, AGENT_B_PROMPT, AGENT_C_PROMPT

class LLMPredictor:
    def __init__(self):
        # 动态计算 .env 文件的绝对路径
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env_path = os.path.join(base_dir, "config", ".env")
        load_dotenv(env_path)
        
        api_key = os.getenv("LLM_API_KEY")
        api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o")
        
        if not api_key:
            logger.error("未找到 LLM_API_KEY，请检查 .env 文件")
            raise ValueError("LLM_API_KEY is not set")
            
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base
        )
        
    def _build_dynamic_rules(self, match_data, handicap_label):
        """
        根据比赛的盘口深度和联赛特征，动态组装 Prompt 规则。
        这极大减轻了单次对话的上下文负担，避免规则冲突。
        """
        rules = [P0_CORE_RULES]
        
        # 1. 动态路由：盘型专属规则
        if handicap_label:
            if "平手" in handicap_label and "平半" not in handicap_label:
                rules.append(HANDICAP_RULES["0"])
            elif "浅盘" in handicap_label:
                rules.append(HANDICAP_RULES["0.25_0.5"])
            elif "中盘" in handicap_label:
                rules.append(HANDICAP_RULES["0.75_1.0"])
            elif "深盘" in handicap_label or "超深盘" in handicap_label:
                rules.append(HANDICAP_RULES["deep"])
                
        # 2. 动态路由：通用变化规则
        rules.append(DYNAMIC_CHANGE_RULES)
        
        # 3. 动态路由：联赛特异性规则 (通过 _get_league_hint 提供)
        league = match_data.get('league', '')
        league_hint = self._get_league_hint(league)
        if league_hint:
            rules.append(f"\n### 🔵 联赛专属规则 ({league})\n- {league_hint}\n")
            
        return "\n".join(rules)

    def _format_match_data(self, match, is_sfc=False):
        """将比赛数据格式化为 Prompt 可读的文本"""
        league = match.get('league', '')
        info = f"- 赛事信息：[{match.get('match_num')}] {league} | {match.get('home_team')} VS {match.get('away_team')}\n"
        info += f"- 比赛时间：{match.get('match_time')}\n"
        
        # 联赛特性提示
        league_hint = self._get_league_hint(league)
        if league_hint:
            info += f"- 联赛特性提示：{league_hint}\n"
        
        recent = match.get('recent_form', {})
        info += "- 基本面：\n"
        if recent.get('standings'):
            info += f"  - 联赛积分与排名：{recent.get('standings')}\n"
            
        # 自动计算场均进失球
        def calc_avg_goals(record_str):
            if not record_str or record_str == "暂无": return ""
            # 匹配例如 "30战18胜5平7负 进59失37"
            m = re.search(r'(\d+)战.*?进(\d+)失(\d+)', record_str)
            if m:
                matches, goals_for, goals_against = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if matches > 0:
                    avg_for = goals_for / matches
                    avg_against = goals_against / matches
                    return f" (场均进球 {avg_for:.2f}, 场均失球 {avg_against:.2f})"
            return ""

        home_record = recent.get('home', '暂无')
        away_record = recent.get('away', '暂无')
        info += f"  - 主队近期战绩：{home_record}{calc_avg_goals(home_record)}\n"
        info += f"  - 客队近期战绩：{away_record}{calc_avg_goals(away_record)}\n"
        info += f"  - 交锋记录：{match.get('h2h_summary', '暂无')}\n"
        if recent.get('injuries') and recent.get('injuries') != "暂无详细伤停数据":
            info += f"  - 伤停与阵容：{recent.get('injuries')}\n"
        if recent.get('macau_recommendation'):
            info += f"  - 澳门心水推荐参考：{recent.get('macau_recommendation')}\n"
        
        # 伤停与阵容
        if recent.get('injuries') and recent.get('injuries') != "暂无详细伤停数据":
            info += f"  - 伤停与阵容：{recent.get('injuries')}\n"

        # --- 雷速体育量化伤停数据 ---
        injuries_detailed = match.get('injuries_detailed', {})
        if injuries_detailed:
            injuries_text = injuries_detailed.get('injuries_text', '')
            if injuries_text:
                # 解析核心缺阵人数
                core_count = len(re.findall(r'(?:跟腱|肌肉|韧带|膝|踝|骨折|重伤|赛季报销)', injuries_text))
                info += f"  - 🔴 **量化伤停影响（雷速体育）**：核心缺阵约 {core_count} 人\n"
                info += f"  - 伤停明细：{injuries_text[:600]}\n"

        # --- 雷速体育进球分布 ---
        goal_dist = match.get('goal_distribution', [])
        if goal_dist and isinstance(goal_dist, list):
            info += f"  - 进球时间分布（雷速体育）：{goal_dist[:18]}\n"

        # --- 雷速体育积分排名 ---
        standings_info = match.get('standings_info', [])
        if standings_info:
            info += f"  - 联赛排名（雷速体育）：{standings_info}\n"

        # --- 雷速体育交锋 ---
        h2h_leisu = match.get('h2h_leisu', [])
        if h2h_leisu:
            info += f"  - 历史交锋比分（雷速体育）：{h2h_leisu[:8]}\n"

        # --- 雷速体育近期战绩 ---
        recent_leisu = match.get('recent_leisu', [])
        if recent_leisu:
            info += f"  - 近期战绩比分（雷速体育）：{recent_leisu[:10]}\n"
        adv_stats = match.get('advanced_stats', {})
        home_adv = adv_stats.get('home', {})
        away_adv = adv_stats.get('away', {})
        
        home_avg_goals = home_adv.get("avg_goals_for")
        away_avg_goals = away_adv.get("avg_goals_for")
        home_avg_conceded = home_adv.get("avg_goals_against")
        away_avg_conceded = away_adv.get("avg_goals_against")
        
        # Fallback 到正则计算
        def parse_avg_goals(text):
            if not text: return None, None
            try:
                import re
                m = re.search(r'(\d+)战.*进(\d+)失(\d+)', text)
                if m:
                    games, goals_for, goals_against = map(int, m.groups())
                    if games > 0:
                        return round(goals_for/games, 1), round(goals_against/games, 1)
            except: pass
            return None, None
            
        if not home_avg_goals and match.get("recent_form", {}).get("home"):
            hf, hc = parse_avg_goals(match["recent_form"]["home"])
            if hf is not None:
                home_avg_goals, home_avg_conceded = hf, hc
                
        if not away_avg_goals and match.get("recent_form", {}).get("away"):
            af, ac = parse_avg_goals(match["recent_form"]["away"])
            if af is not None:
                away_avg_goals, away_avg_conceded = af, ac

        info += f"  - 高阶攻防数据：\n"
        info += f"    - 主队：场均进球 {home_avg_goals or '未知'}, 场均失球 {home_avg_conceded or '未知'}\n"
        info += f"    - 客队：场均进球 {away_avg_goals or '未知'}, 场均失球 {away_avg_conceded or '未知'}\n"

        if home_adv.get('avg_shots') or away_adv.get('avg_shots'):
            info += f"    - 主队：场均射门 {home_adv.get('avg_shots', '未知')}, 场均射正 {home_adv.get('avg_shots_on_target', '未知')}, 场均xG {home_adv.get('avg_xG', '未知')}\n"
            info += f"    - 客队：场均射门 {away_adv.get('avg_shots', '未知')}, 场均射正 {away_adv.get('avg_shots_on_target', '未知')}, 场均xG {away_adv.get('avg_xG', '未知')}\n"
        
        info += "- 盘赔数据：\n"
        odds = match.get('odds', {})
        
        if odds.get('nspf'):
            info += f"  - 竞彩不让球赔率(胜/平/负)：{odds.get('nspf', [])}\n"
        if odds.get('spf'):
            info += f"  - 竞彩让球({odds.get('rangqiu')})赔率(胜/平/负)：{odds.get('spf', [])}\n"
            
        bqc = odds.get('bqc', {})
        if bqc:
            info += f"  - 半全场赔率参考(平平/平胜/平负等)：{bqc}\n"
        
        asian = match.get('asian_odds', {})
        if 'macau' in asian:
            info += f"  - 澳门亚指：初盘 [{asian['macau'].get('start')}] -> 即时盘 [{asian['macau'].get('live')}]\n"
        if 'bet365' in asian:
            info += f"  - Bet365亚指：初盘 [{asian['bet365'].get('start')}] -> 即时盘 [{asian['bet365'].get('live')}]\n"
            
        # 盘赔异动检测 (结构化摘要)
        asian_change = self._detect_odds_change(asian)
        if asian_change:
            info += f"  - 盘赔异动摘要：{asian_change}\n"
        
        # 盘型标注（帮助LLM快速定位适用规则）
        handicap_label = self._classify_handicap(odds.get('rangqiu','0'), asian)
        if handicap_label:
            info += f"  - 亚指盘型：{handicap_label}\n"
        
        # 1. 🚨 超深盘死水预警 (针对两球以上盘口)
        deep_water_warning = self._detect_deep_water_trap(asian)
        if deep_water_warning:
            info += f"  - 🚨 **超深盘死水预警**：{deep_water_warning}\n"
            
        # 2. 🔴 半球生死盘异动预警
        half_ball_warning = self._detect_half_ball_trap(asian, odds)
        if half_ball_warning:
            info += f"  - 🔴 **半球生死盘预警**：{half_ball_warning}\n"
            
        # 3. ⚠️ 平手盘水位僵持检测
        flat_water_warning = self._detect_flat_water_static(asian)
        if flat_water_warning:
            info += f"  - ⚠️ **平手盘水位僵持预警**：{flat_water_warning}\n"
        
        # 4. 🚨 赔率方向矛盾检测
        odds_conflict = self._detect_odds_conflict(odds, asian)
        if odds_conflict:
            info += f"  - 🚨 **赔率方向矛盾预警**：{odds_conflict}\n"
        
        # 5. 🔴 盘水背离检测（升盘+升水诱上信号）
        divergence_warning = self._detect_handicap_water_divergence(asian)
        if divergence_warning:
            info += f"  - 🔴 **盘水背离预警（强队虚热/诱上信号）**：{divergence_warning}\n"
            
        # 6. 🔴 浅盘临场升水诱下预警 (04-30复盘新增)
        shallow_water_warning = self._detect_shallow_water_trap(asian, odds)
        if shallow_water_warning:
            info += f"  - 🔴 **浅盘升水诱下预警**：{shallow_water_warning}\n"
            
        # 7. 🚨 欧亚背离量化预警 (V3架构新增)
        euro_asian_warning = self._detect_euro_asian_divergence(odds, asian)
        if euro_asian_warning:
            info += f"  - 🚨 **欧亚背离量化预警**：{euro_asian_warning}\n"
            
        return info

    @staticmethod
    def _detect_deep_water_trap(asian):
        """
        检测超深盘（1.75及以上）的死水陷阱（04-29复盘新增）。
        超深盘下若水位毫无波动，往往是机构张网以待诱导强队，极易出冷平。
        """
        if not asian:
            return ""
        macau = asian.get('macau', {})
        start = macau.get('start', '')
        live = macau.get('live', '')
        if not start or not live or '|' not in start:
            return ""
            
        # 检查是否为超深盘 (1.75及以上)
        handicap_raw = start.split('|')[1].strip().replace(' ', '')
        deep_keywords = ['球半/两球', '两球', '两球/两球半', '两球半', '三球']
        is_deep = any(k in handicap_raw for k in deep_keywords)
        if not is_deep:
            return ""
            
        # 提取两端水位
        def get_waters(line):
            parts = line.split('|')
            if len(parts) < 3: return None, None
            try:
                w1 = float(parts[0].strip().replace('↑','').replace('↓',''))
                w2 = float(parts[2].strip().replace('↑','').replace('↓',''))
                return w1, w2
            except:
                return None, None
                
        w1_start, w2_start = get_waters(start)
        w1_live, w2_live = get_waters(live)
        if w1_start is None or w1_live is None:
            return ""
            
        # 计算水位变化绝对值
        gap_up = abs(w1_live - w1_start)
        gap_down = abs(w2_live - w2_start)
        
        if gap_up <= 0.02 and gap_down <= 0.02:
            return (f"初盘[{handicap_raw}]为超深盘，但临场水位几乎毫无波动（死水一潭）。"
                    "超深盘不降水规避风险，说明机构在利用深盘诱导买入强队，"
                    "**这是极其典型的冷平/冷负温床，必须在不让球玩法中防范平局或客胜爆大冷！**")
        return ""

    @staticmethod
    def _detect_half_ball_trap(asian, odds):
        """
        检测半球生死盘的水位异动与资金流向（04-29复盘新增）。
        半球盘赢球即赢盘，打平即全输。
        1. 升水诱导：半球盘上盘水位异常升高 -> 大众资金买强队，机构顺势提升赔付（诱上），防客胜。
        2. 降水阻盘：半球升半一且降水 -> 机构真怕了，阻挡买入，强队稳胜。
        """
        if not asian:
            return ""
        macau = asian.get('macau', {})
        start = macau.get('start', '')
        live = macau.get('live', '')
        if not start or not live or '|' not in start or '|' not in live:
            return ""
            
        # 确认初盘是半球盘
        start_h = start.split('|')[1].strip().replace(' ', '')
        if start_h not in ['半球', '受半球']:
            return ""
            
        live_h = live.split('|')[1].strip().replace(' ', '')
        
        # 提取让球方(上盘)水位变化
        def get_upper_water(line, is_home_yield):
            parts = line.split('|')
            if len(parts) < 3: return None
            try:
                # 主队让球取左边水位，客队让球取右边水位
                w_str = parts[0] if is_home_yield else parts[2]
                return float(w_str.strip().replace('↑','').replace('↓',''))
            except:
                return None
                
        is_home_yield = '受' not in start_h
        start_w = get_upper_water(start, is_home_yield)
        live_w = get_upper_water(live, is_home_yield)
        
        if start_w is None or live_w is None:
            return ""
            
        water_diff = live_w - start_w
        
        # 场景1: 维持半球盘，但上盘水位异常飙升 (诱导大热)
        if start_h == live_h and water_diff >= 0.08:
            return (f"初盘和即时盘均维持【{start_h}】生死盘，但让球方水位异常飙升(+{water_diff:.3f})！"
                    "大众资金蜂拥强队，机构顺势提升赔付门槛（诱上）。此时极易打出下盘，**坚决防范下盘直接赢球（甚至大比分），严禁单选上盘胜！**")
                    
        # 场景2: 升盘且降水 (真实阻盘)
        is_upgrade = ('半球/一球' in live_h and '受' not in live_h) if is_home_yield else ('受半球/一球' in live_h)
        if is_upgrade and water_diff <= -0.05:
            return (f"从【{start_h}】升盘至【{live_h}】，且让球方水位大幅下降({water_diff:.3f})！"
                    "机构在通过升盘降水真实阻挡买入强队的资金。抛弃诱盘阴谋论，**让球方实力打出概率极高，首选上盘胜！**")
                    
        return ""

    @staticmethod
    def _detect_odds_conflict(odds, asian):
        """
        检测竞彩让球方向与亚指让球方向、赔率高低的矛盾。
        当"谁是强方"在不同数据源之间存在根本分歧时，触发最高级预警。
        """
        if not odds or not asian:
            return ""
        
        rq_str = odds.get('rangqiu', '0')
        nspf = odds.get('nspf', [])
        
        try:
            rq = int(float(rq_str))
        except:
            return ""
        
        # 竞彩方向: rq < 0 = 主队让球(主队是强方), rq > 0 = 客队让球(客队是强方)
        cai_home_strong = (rq < 0)
        
        # 亚指方向检测：从澳门初盘中提取
        macau_start = asian.get('macau', {}).get('start', '')
        # 含"受"字 = 主队受让 = 客队是强方
        asian_home_strong = None
        if '受' in macau_start:
            asian_home_strong = False  # 主队受让，客队强
        elif any(d in macau_start for d in ['平手/', '半球', '一球', '球半', '两球']):
            if not macau_start.startswith('受'):
                asian_home_strong = True  # 主队让球，主队强
        
        # 赔率方向检测
        odds_home_strong = None
        if len(nspf) == 3:
            try:
                home_odds, _, away_odds = float(nspf[0]), float(nspf[1]), float(nspf[2])
                if home_odds < away_odds - 0.3:
                    odds_home_strong = True
                elif away_odds < home_odds - 0.3:
                    odds_home_strong = False
            except:
                pass
        
        conflicts = []
        
        # 竞彩 vs 亚指方向冲突
        if asian_home_strong is not None and cai_home_strong != asian_home_strong:
            conflicts.append(
                f"竞彩让球({rq})认为{'主队' if cai_home_strong else '客队'}是强方，"
                f"但亚指盘口显示{'主队' if asian_home_strong else '客队'}是强方——"
                f"两大机构对实力判断完全相反！"
            )
        
        # 竞彩赔率 vs 竞彩让球方向冲突
        if odds_home_strong is not None and odds_home_strong != cai_home_strong:
            conflicts.append(
                f"竞彩让球({rq})指向{'主队' if cai_home_strong else '客队'}优势，"
                f"但竞彩赔率却显示{'客队' if cai_home_strong else '主队'}胜赔更低"
                f"(主胜{nspf[0]} vs 客胜{nspf[2]})——赔率与让球自相矛盾！"
            )
        
        return ' | '.join(conflicts) if conflicts else ""

    @staticmethod
    def _classify_handicap(rangqiu_str, asian):
        """从亚指文本提取盘型标签，用于Prompt中帮助LLM定位规则"""
        handicap_text = ""
        macau_start = asian.get('macau', {}).get('start', '') if asian else ''
        if macau_start and '|' in macau_start:
            handicap_text = macau_start.split('|')[1].strip()
        if not handicap_text:
            return ""
        ht = handicap_text.replace(' ', '')
        mapping = [
            ('受平手/半球', '受平半(浅盘)'), ('平手/半球', '平半(浅盘)'),
            ('平手', '平手'), ('受半球/一球', '受半一(中深盘)'), ('半球/一球', '半一(中盘)'),
            ('受一球/球半', '受一球/球半(深盘)'), ('一球/球半', '一球/球半(深盘)'),
            ('受半球', '受半球(中盘)'), ('半球', '半球(浅盘)'),
            ('受一球', '受一球(深盘)'), ('一球', '一球(中深盘)'),
            ('受球半', '受球半(深盘)'), ('球半', '球半(深盘)'),
            ('受两球', '受两球(超深盘)'), ('两球', '两球(超深盘)'),
            ('两球半', '两球半(超深盘)'),
        ]
        for pattern, label in mapping:
            if pattern in ht:
                return label
        return ""

    @staticmethod
    def _detect_flat_water_static(asian):
        """检测平手盘水位僵持——市场均衡≠平局倾向"""
        if not asian:
            return ""
        macau = asian.get('macau', {})
        start = macau.get('start', '')
        live = macau.get('live', '')
        if not start or not live:
            return ""
        # 检查是否为平手盘
        if '|' not in start:
            return ""
        start_handicap = start.split('|')[1].strip().replace(' ', '')
        if '平手' not in start_handicap or '平手/' in start_handicap:
            return ""
        # 提取两端水位
        def get_waters(line):
            parts = line.split('|')
            if len(parts) < 3: return None, None
            try:
                w1 = float(parts[0].strip().replace('↑','').replace('↓',''))
                w2 = float(parts[2].strip().replace('↑','').replace('↓',''))
                return w1, w2
            except:
                return None, None
        w1_start, w2_start = get_waters(start)
        w1_live, w2_live = get_waters(live)
        if w1_start is None or w1_live is None:
            return ""
        # 计算水位变化
        gap_up = abs(w1_live - w1_start)
        gap_down = abs(w2_live - w2_start)
        if gap_up < 0.06 and gap_down < 0.06:
            return "初盘→即时盘两端水位均无明显变化，市场完全均衡。这不是'看好平局'的信号——任何赛果（包括2-6屠杀）都可能发生。严禁排除任一选项，三选保留≥15%。"
        return ""

    @staticmethod
    def _detect_odds_change(asian):
        """解析亚指初盘->即时盘变化，输出结构化摘要"""
        if not asian:
            return ""
        
        def parse_asian_line(line):
            """解析"水位 | 盘口 | 水位"格式"""
            parts = line.split('|')
            if len(parts) < 3:
                return None
            water_up_raw = parts[0].strip().replace('↑','').replace('↓','')
            handicap_raw = parts[1].strip()
            water_down_raw = parts[2].strip().replace('↑','').replace('↓','')
            try:
                water_up = float(water_up_raw)
                water_down = float(water_down_raw)
            except:
                return None
            # 提取箭头方向
            up_arrow = '↑' if '↑' in parts[0] else ('↓' if '↓' in parts[0] else '')
            down_arrow = '↑' if '↑' in parts[2] else ('↓' if '↓' in parts[2] else '')
            return {'water_up': water_up, 'handicap': handicap_raw, 'water_down': water_down,
                    'up_arrow': up_arrow, 'down_arrow': down_arrow}
        
        handicap_map = {
            '平手': 0, '平手/半球': 0.25, '半球': 0.5, '半球/一球': 0.75,
            '一球': 1.0, '一球/球半': 1.25, '球半': 1.5, '球半/两球': 1.75,
            '两球': 2.0, '两球/两球半': 2.25, '两球半': 2.5, '受平手/半球': -0.25,
            '受半球': -0.5, '受半球/一球': -0.75, '受一球': -1.0
        }
        
        def handicap_to_val(h):
            return handicap_map.get(h.replace(' ',''), None)
        
        changes = []
        for broker in ['macau', 'bet365']:
            if broker not in asian:
                continue
            s = parse_asian_line(asian[broker].get('start', ''))
            l = parse_asian_line(asian[broker].get('live', ''))
            if not s or not l:
                continue
            
            broker_name = '澳门' if broker == 'macau' else 'Bet365'
            parts_summary = []
            
            # 盘口变化
            h_s = handicap_to_val(s['handicap'])
            h_l = handicap_to_val(l['handicap'])
            if h_s is not None and h_l is not None:
                if h_l > h_s:
                    parts_summary.append(f"升盘({s['handicap']}→{l['handicap']})")
                elif h_l < h_s:
                    parts_summary.append(f"退盘({s['handicap']}→{l['handicap']})")
            
            # 上盘水位变化 (让球方)
            w_diff = l['water_up'] - s['water_up']
            if abs(w_diff) >= 0.03:
                direction = '↑升水' if w_diff > 0 else '↓降水'
                parts_summary.append(f"上盘水位{direction}({s['water_up']:.2f}→{l['water_up']:.2f})")
            
            # 下盘水位
            wd_diff = l['water_down'] - s['water_down']
            if abs(wd_diff) >= 0.03:
                direction = '↑升水' if wd_diff > 0 else '↓降水'
                parts_summary.append(f"下盘水位{direction}({s['water_down']:.2f}→{l['water_down']:.2f})")
            
            if parts_summary:
                changes.append(f"{broker_name}: {'；'.join(parts_summary)}")
        
        return ' | '.join(changes) if changes else ""

    @staticmethod
    def _detect_handicap_water_divergence(asian):
        """
        检测"升盘+升水"背离信号（04-28复盘新增）。
        升盘理论上应伴随降水位，若水位反升说明机构并不真正看好让球方。
        重点关注: 半一→一球 或 半球→半一 且上盘水位抬升≥0.05
        """
        if not asian:
            return ""
        
        handicap_map = {
            '平手': 0, '平手/半球': 0.25, '半球': 0.5, '半球/一球': 0.75,
            '一球': 1.0, '一球/球半': 1.25, '球半': 1.5, '球半/两球': 1.75,
            '两球': 2.0, '两球/两球半': 2.25, '两球半': 2.5,
            '受平手/半球': -0.25, '受半球': -0.5, '受半球/一球': -0.75, '受一球': -1.0,
            '受一球/球半': -1.25, '受球半': -1.5
        }
        
        def parse(line):
            parts = line.split('|')
            if len(parts) < 3: return None
            try:
                w1 = float(parts[0].strip().replace('↑','').replace('↓',''))
                h = parts[1].strip()
                w2 = float(parts[2].strip().replace('↑','').replace('↓',''))
                return (w1, h, w2)
            except: return None
        
        warnings = []
        for broker in ['macau', 'bet365']:
            data = asian.get(broker, {})
            s = parse(data.get('start', ''))
            l = parse(data.get('live', ''))
            if not s or not l: continue
            
            sw1, sh, sw2 = s
            lw1, lh, lw2 = l
            
            hs = handicap_map.get(sh.replace(' ',''), None)
            hl = handicap_map.get(lh.replace(' ',''), None)
            if hs is None or hl is None: continue
            
            # 检测升盘
            is_upgrade = hl > hs
            # 检测上盘水位上升（让球方/更优方水位）
            water_rise = lw1 - sw1 if hs >= 0 else lw2 - sw2
            
            if is_upgrade and water_rise >= 0.05:
                broker_name = '澳门' if broker == 'macau' else 'Bet365'
                level = '🔴高危' if water_rise >= 0.08 else '⚠️预警'
                warnings.append(
                    f"{broker_name}{level}: 盘口从{sh}升至{lh}，"
                    f"但让球方水位同步抬升{(water_rise*100):.0f}个点——"
                    f"机构升盘却不降水，表明并非真实看好让球方，"
                    f"此盘水背离是诱上信号，应坚决防下盘（推平/负）。"
                )
            elif is_upgrade and water_rise >= 0.03:
                broker_name = '澳门' if broker == 'macau' else 'Bet365'
                warnings.append(
                    f"{broker_name}: 盘口从{sh}升至{lh}，"
                    f"让球方水位微升{(water_rise*100):.0f}个点——"
                    f"升盘未伴随明显降水，信心不扎实，需谨慎对待让球方取胜。"
                )
        
        return ' | '.join(warnings) if warnings else ""

    @staticmethod
    def _detect_euro_asian_divergence(odds, asian):
        """
        计算欧赔隐含概率，并对比实际亚指，检测“欧亚背离”冷门预警。
        逻辑：
        1. 从竞彩不让球赔率 (NSPF) 提取主平负赔率。
        2. 计算返还率 (Return Rate) = 1 / (1/win + 1/draw + 1/lose)。
        3. 计算真实隐含概率 = (1/odds) * Return Rate。
        4. 根据主队胜率区间映射“理论亚盘”。
        5. 对比实际澳门初盘，若“理论开深盘，实际开浅盘”，则是典型诱导，极大可能出下盘。
        """
        if not odds or not asian:
            return ""
            
        nspf = odds.get('nspf', [])
        if len(nspf) != 3:
            return ""
            
        try:
            # 1. 获取竞彩赔率 (默认顺序: 胜, 平, 负)
            home_odds = float(nspf[0])
            draw_odds = float(nspf[1])
            away_odds = float(nspf[2])
            
            # 2. 计算返还率
            implied_prob_sum = (1 / home_odds) + (1 / draw_odds) + (1 / away_odds)
            return_rate = 1 / implied_prob_sum
            
            # 3. 计算真实胜率 (剔除水钱)
            home_prob = (1 / home_odds) * return_rate
            away_prob = (1 / away_odds) * return_rate
            
            # 确定谁是强势方
            strong_prob = max(home_prob, away_prob)
            is_home_strong = home_prob >= away_prob
            
            # 4. 理论亚盘映射表 (胜率区间 -> 理论盘口深度)
            # 这套映射基于业内标准的欧洲赔率转亚洲让球公式
            theory_handicap_val = 0.0
            theory_handicap_str = "平手"
            
            if strong_prob >= 0.75:
                theory_handicap_val = 1.5
                theory_handicap_str = "球半"
            elif strong_prob >= 0.68:
                theory_handicap_val = 1.25
                theory_handicap_str = "一球/球半"
            elif strong_prob >= 0.62:
                theory_handicap_val = 1.0
                theory_handicap_str = "一球"
            elif strong_prob >= 0.55:
                theory_handicap_val = 0.75
                theory_handicap_str = "半球/一球"
            elif strong_prob >= 0.48:
                theory_handicap_val = 0.5
                theory_handicap_str = "半球"
            elif strong_prob >= 0.40:
                theory_handicap_val = 0.25
                theory_handicap_str = "平手/半球"
            else:
                theory_handicap_val = 0.0
                theory_handicap_str = "平手"
                
            # 理论盘口如果是客队强，加上负号
            if not is_home_strong:
                theory_handicap_val = -theory_handicap_val
                
            # 5. 获取实际澳门初盘
            macau_start = asian.get('macau', {}).get('start', '')
            if not macau_start or '|' not in macau_start:
                return ""
                
            actual_handicap_str = macau_start.split('|')[1].strip().replace(' ', '')
            
            # 实际盘口转数值
            handicap_map = {
                '平手': 0, '平手/半球': 0.25, '半球': 0.5, '半球/一球': 0.75,
                '一球': 1.0, '一球/球半': 1.25, '球半': 1.5, '球半/两球': 1.75,
                '两球': 2.0, '两球/两球半': 2.25, '两球半': 2.5, 
                '受平手/半球': -0.25, '受半球': -0.5, '受半球/一球': -0.75, '受一球': -1.0,
                '受一球/球半': -1.25, '受球半': -1.5, '受球半/两球': -1.75, '受两球': -2.0
            }
            
            actual_handicap_val = handicap_map.get(actual_handicap_str, None)
            if actual_handicap_val is None:
                return ""
                
            # 6. 对比与预警
            # 如果主队是强势方，理论盘口 > 实际盘口 (即理论应该让深盘，实际让浅了) -> 诱导主队，看衰主队
            divergence = theory_handicap_val - actual_handicap_val
            
            warnings = []
            team_strong = "主队" if is_home_strong else "客队"
            
            # 背离达到 0.5 (即相差两个盘口，比如理论一球，实际半球)
            if abs(divergence) >= 0.5:
                if is_home_strong and divergence > 0:
                    warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，理论应开【{theory_handicap_str}】；但实际亚指初盘仅开【{actual_handicap_str}】。欧亚严重背离！实际盘口远浅于理论实力，机构在刻意降低买入{team_strong}的门槛（诱导）。极大概率爆冷，必须防范{team_strong}不胜！")
                elif not is_home_strong and divergence < 0:
                    warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，理论应开受让【{theory_handicap_str}】；但实际亚指初盘仅开【{actual_handicap_str}】。欧亚严重背离！机构刻意降低{team_strong}让步门槛诱导买入。极大概率爆冷，必须防范{team_strong}不胜！")
                elif is_home_strong and divergence < 0:
                     warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，理论仅能支撑【{theory_handicap_str}】；但实际亚指初盘强开【{actual_handicap_str}】深盘。机构在利用深盘和高门槛阻挡资金买入{team_strong}。这是典型的“阻上”手法，{team_strong}大概率能打出！")
                elif not is_home_strong and divergence > 0:
                     warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，理论仅能支撑受让【{theory_handicap_str}】；但实际亚指初盘强开【{actual_handicap_str}】深盘。这是典型的“阻上”手法，{team_strong}大概率能打出！")
            
            return " | ".join(warnings)
            
        except Exception as e:
            return ""

    @staticmethod
    def _detect_shallow_water_trap(asian, odds):
        """
        检测浅盘（平手、平半）临场升水诱下陷阱（04-30复盘新增）。
        当主队水位从低水区（≤0.85）剧烈攀升至高水区（≥1.00），且盘口未跟随调整时，此形态极度疑似机构在利用“升水”制造主队获胜不稳的恐慌感。
        """
        if not asian or not odds:
            return ""
            
        macau = asian.get('macau', {})
        start = macau.get('start', '')
        live = macau.get('live', '')
        
        if not start or not live or '|' not in start or '|' not in live:
            return ""
            
        # 确认盘口
        start_h = start.split('|')[1].strip().replace(' ', '')
        live_h = live.split('|')[1].strip().replace(' ', '')
        
        # 只针对平手、平手/半球
        if start_h not in ['平手', '平手/半球', '受平手/半球']:
            return ""
            
        # 盘口未变
        if start_h != live_h:
            return ""
            
        # 获取主队水位 (澳门数据：主队水位 | 盘口 | 客队水位)
        def get_home_water(line):
            parts = line.split('|')
            if len(parts) < 3: return None
            try:
                return float(parts[0].strip().replace('↑','').replace('↓',''))
            except:
                return None
                
        start_w = get_home_water(start)
        live_w = get_home_water(live)
        
        if start_w is None or live_w is None:
            return ""
            
        # 触发条件：初盘低水(≤0.85)，临场高水(≥1.00)
        if start_w <= 0.85 and live_w >= 1.00:
            nspf = odds.get('nspf', [])
            odds_str = ""
            if len(nspf) == 3:
                odds_str = f"（当前主胜赔率 {nspf[0]}）"
                
            return (f"盘口维持【{start_h}】浅盘，但主队水位从初盘低水({start_w})剧烈攀升至即时高水({live_w})！"
                    f"此为典型的“低水升水诱下盘”操作，机构在利用“升水”这一表面利空形态，制造主队“让球无力”的恐慌感，从而将热度驱赶至客队方向。"
                    f"{odds_str} 严禁仅因水位大涨得出“主队不胜”的结论，必须强制增加对主队获胜的考量权重！")
            
        return ""

    @staticmethod
    def _get_league_hint(league):
        """返回联赛特异性提示，帮助LLM快速校准预期"""
        if not league:
            return ""
        lg = league.strip()
        # 防守型联赛 (小球倾向)
        if any(d in lg for d in ['法甲', '法乙', '葡超', '西甲']):
            return "该联赛为防守型联赛，深盘优先防小球和赢球输盘，忌盲目推3+球"
        # 大球联赛 (攻击倾向)
        if any(d in lg for d in ['美职', '澳超', '荷甲', '荷乙']):
            return "该联赛为大开大合型，攻击力碾压时敢于推大比分和让胜"
        # 次级联赛 (盘口操控更严重)
        if any(d in lg for d in ['英冠', '英甲', '德乙', '法乙', '日乙', 'K2']):
            return "次级联赛盘口操纵更严重，退盘升水信号务必高度重视"
        # 北欧冷门联赛
        if any(d in lg for d in ['挪超', '瑞超', '芬超']):
            return "北欧联赛主场优势极显著，赛季初冷门频发。**挪超主队场均进球>2，客队远征疲惫，深盘下倾向主队屠杀而非下盘。**"
        # 杯赛（战意不对称导致突变）
        if any(d in lg for d in ['英足总杯', '足总杯', '杯']):
            return "杯赛战意不对称严重，强队轮换+弱队全主力=冷门温床，但强队半主力+主场优势仍可小胜"
        # 沙特联赛 (04-28复盘新增：盘口变动敏感性高)
        if any(d in lg for d in ['沙特']):
            return "沙特联赛盘口变动陷阱多，升盘+升水组合(=盘水背离)是诱上高危信号。**半一升一球+高水时必须坚决防下盘，推平/负。** 此联赛中升盘信号不可轻信为'阻上'——该联赛的升盘诱导比例远高于阻上。"
        # 日韩联赛
        if any(d in lg for d in ['日职', '韩K']):
            return "日韩联赛节奏快、战意受盘外因素影响大，注意临场变数"
        # 英冠
        if any(d in lg for d in ['英冠']):
            return "英冠身体对抗激烈，主场优势大，平半盘下主队不败概率高"
        # 五大联赛及葡超（主流联赛，水位示弱常为诱下）
        if any(d in lg for d in ['英超', '意甲', '德甲']):
            return "主流联赛中盘口升水/客队降水常是机构诱下手段，主队基本面不差时勿轻信示弱信号，首选胜/平"
        # 其他二线联赛（如葡超、比甲、瑞士超等，盘赔背离预警）
        return "非五大联赛关注度低，资金体量小，极易被机构操控。若强队深盘出现水位不降反升（盘水背离），多为虚假繁荣的诱导，坚决防范下盘冷门！"

    @staticmethod
    def parse_prediction_details(prediction_text):
        """提取详细的预测结果，拆分为推荐、进球数、比分、信心三个部分"""
        details = {
            'recommendation': '暂无',
            'recommendation_nspf': '暂无',
            'recommendation_rq': '暂无',
            'reason': '暂无',
            'goals': '暂无',
            'score': '暂无',
            'confidence': '暂无',
            'goals_confidence': '暂无'
        }
        if not prediction_text:
            return details
            
        import re
        
        lines = prediction_text.split('\n')
        recommendations = []
        nspf_recommendations = []
        rq_recommendations = []
        
        for line in lines:
            line = line.strip()
            line_clean = line.replace('**','').replace('*','').strip()
            if not line_clean:
                continue
                
            if '不让球推荐' in line_clean or '竞彩推荐（不让球）' in line_clean or ('竞彩推荐' in line_clean and '不让球' in line_clean) or ('竞彩推荐' in line_clean and '让球' not in line_clean.split('：')[0].split(':')[0]) or ('不让球：' in line_clean or '不让球:' in line_clean):
                parts = re.split(r'[：:]', line_clean, maxsplit=1)
                if len(parts) > 1:
                    full_rec = re.sub(r'[\*]', '', parts[1].strip())
                    # 匹配任何形式的“(注：...)”或“（注：...）”一直到行尾
                    full_rec = re.sub(r'[（\(]注[：:].*$', '', full_rec).strip()
                    full_rec = re.sub(r'——.*$', '', full_rec).strip()
                    bracket_match = re.search(r'[\[【]([^\]】]+)[\]】]', full_rec)
                    if bracket_match:
                        full_rec = bracket_match.group(1).strip()
                    sub_parts = re.split(r'[。！？]', full_rec, maxsplit=1)
                    nspf_recommendations.append(sub_parts[0].strip())
                    if len(sub_parts) > 1 and sub_parts[1].strip() and details['reason'] == '暂无':
                        details['reason'] = sub_parts[1].strip()

            elif '让球推荐' in line or '竞彩推荐（让球' in line or '竞彩让球推荐' in line or '让球(-' in line or '让球(+' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    full_rec = re.sub(r'[\*]', '', parts[1].strip())
                    # 匹配任何形式的“(注：...)”或“（注：...）”一直到行尾
                    full_rec = re.sub(r'[（\(]注[：:].*$', '', full_rec).strip()
                    full_rec = re.sub(r'——.*$', '', full_rec).strip()
                    bracket_match = re.search(r'[\[【]([^\]】]+)[\]】]', full_rec)
                    if bracket_match:
                        full_rec = bracket_match.group(1).strip()
                    sub_parts = re.split(r'[。！？]', full_rec, maxsplit=1)
                    rq_recommendations.append(sub_parts[0].strip())
                    if len(sub_parts) > 1 and sub_parts[1].strip() and details['reason'] == '暂无':
                        details['reason'] = sub_parts[1].strip()

            elif '逻辑' in line and ('：' in line or ':' in line) and ('推荐' not in line):
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1 and details['reason'] == '暂无':
                    details['reason'] = re.sub(r'[\*]', '', parts[1].strip())

            elif '竞彩推荐' in line or '推荐：' in line or '推荐:' in line:
                if '：' in line:
                    parts = line.rsplit('：', 1)
                elif ':' in line:
                    parts = line.rsplit(':', 1)
                else:
                    parts = [line]
                
                prefix = parts[0]
                prefix_info = ""
                match_prefix = re.search(r'[（(]([^）)]+)[）)]', prefix)
                if match_prefix:
                    clean_prefix = match_prefix.group(1).replace('：', ' ').replace(':', ' ')
                    prefix_info = f"({clean_prefix}) "
                
                if len(parts) > 1:
                    full_rec = parts[-1].strip()
                    full_rec = re.sub(r'[\*]', '', full_rec)
                    
                    sub_parts = re.split(r'[。！？]', full_rec, maxsplit=1)
                    rec_part = sub_parts[0].strip()
                    
                    if prefix_info and prefix_info.strip() not in rec_part:
                        recommendations.append(f"{prefix_info}{rec_part}")
                    else:
                        recommendations.append(rec_part)
                    
                    if len(sub_parts) > 1 and sub_parts[1].strip():
                        if details['reason'] == '暂无':
                            details['reason'] = sub_parts[1].strip()
                    
            elif '进球数置信度' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    conf_str = parts[1].strip()
                    details['goals_confidence'] = re.sub(r'[\*]', '', conf_str)
                    
            elif '进球数参考' in line or ('进球数' in line and '预测' not in line and '置信度' not in line):
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    goals_str = parts[1].strip()
                    details['goals'] = re.sub(r'[\*]', '', goals_str)
                    
            elif '比分参考' in line or '比分' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    score_str = parts[1].strip()
                    details['score'] = re.sub(r'[\*]', '', score_str)
                    
            elif '竞彩置信度' in line or ('置信度' in line and '进球数' not in line) or '信心' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    conf_str = parts[1].strip()
                    details['confidence'] = re.sub(r'[\*]', '', conf_str)
                    
        if nspf_recommendations:
            details['recommendation_nspf'] = " | ".join(nspf_recommendations)
        if rq_recommendations:
            details['recommendation_rq'] = " | ".join(rq_recommendations)
            
        # Combine into general recommendation if found
        if recommendations:
            details['recommendation'] = " | ".join(recommendations)
        elif nspf_recommendations or rq_recommendations:
            combined = []
            if nspf_recommendations:
                combined.append("不让球: " + " | ".join(nspf_recommendations))
            if rq_recommendations:
                combined.append("让球: " + " | ".join(rq_recommendations))
            details['recommendation'] = " ; ".join(combined)
            
        # 提取完整的最终预测段落作为复盘理由
        match_final = re.search(r'(?:🎯\s*)?最终预测\s*(.*?)(?=\n\s*(?:⚽\s*)?进球数预测|$)', prediction_text, re.DOTALL)
        if match_final:
            clean_reason = match_final.group(1).strip()
            clean_reason = re.sub(r'^\*+', '', clean_reason)
            details['reason'] = clean_reason
                    
        if details['reason'] == '暂无':
            reason_match = re.search(r'(?:【风险提示】|风险提示|核心逻辑)[：:]?\s*([^\n]+)', prediction_text)
            if reason_match:
                details['reason'] = re.sub(r'[\*]', '', reason_match.group(1).strip())
                
        if details['reason'] == '暂无':
            details['reason'] = prediction_text[-300:]  # 兜底截取最后一部分
                
        # 兜底策略: 如果行级解析未找到NSPF，在全文中搜索推荐关键词
        if not nspf_recommendations:
            tail = prediction_text[-1500:]  # 搜索尾部1500字符
            for pattern in [r'(?:不让球推荐|竞彩推荐.*不让球|竞彩推荐(?!.*让球))\s*[：:]\s*([^\n]{2,20})',
                          r'最终推荐[：:]\s*([^\n]{2,30})',
                          r'推荐[：:]\s*(.{1,3}胜.{0,10})',
                          r'首选[：:]?\s*(.{1,3}胜).{0,10}']:
                m = re.search(pattern, tail)
                if m:
                    rec = re.sub(r'[\*\s]', '', m.group(1))
                    if any(d in rec for d in ['胜','平','负']):
                        nspf_recommendations.append(rec)
                        break
            # 终极兜底: 在全文尾部搜索 "胜/平/负" 三字中最频繁出现且有推荐的模式
            if not nspf_recommendations:
                final_section = prediction_text[-800:]
                # 找类似 "胜 (80%)" 或 "主胜(70%)" 的高置信度单一推荐
                m2 = re.search(r'(?:主)?胜\s*[（(]\s*(\d+)\s*%?\s*[）)]', final_section)
                m3 = re.search(r'(?:客)?胜\s*[（(]\s*(\d+)\s*%?\s*[）)]', final_section)
                m4 = re.search(r'平\s*[（(]\s*(\d+)\s*%?\s*[）)]', final_section)
                if m2 or m3 or m4:
                    parts = []
                    if m2: parts.append(f"胜({m2.group(1)}%)")
                    if m3: parts.append(f"负({m3.group(1)}%)")  # 客胜=负
                    if m4: parts.append(f"平({m4.group(1)}%)")
                    if parts:
                        nspf_recommendations.append(" / ".join(parts))
            
        if nspf_recommendations:
            details['recommendation_nspf'] = " | ".join(nspf_recommendations)
                
        if details['recommendation'] == '暂无':
            text_tail = prediction_text[-max(len(prediction_text)//5, 100):]
            scores = {
                '主胜': len(re.findall(r'(?:主胜|主队胜|推荐.*胜|看好.*主队)', text_tail)),
                '客胜': len(re.findall(r'(?:客胜|客队胜|推荐.*负|看好.*客队)', text_tail)),
                '平局': len(re.findall(r'(?:平局|战平|防平|握手言和)', text_tail))
            }
            if max(scores.values()) > 0:
                details['recommendation'] = max(scores, key=scores.get)
                
        return details

    def generate_article(self, match_data, prediction_text, all_matches=None):
        """
        将分析报告转换为微信公众号文章 (对标严谨专业的赛事前瞻风格)，并使用真实的比赛作为扫盘列表。
        """
        # 加载敏感词替换字典
        sensitive_rules = ""
        dict_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "wechat", "sensitive_dict.json")
        try:
            if os.path.exists(dict_path):
                with open(dict_path, 'r', encoding='utf-8') as f:
                    sensitive_dict = json.load(f)
                
                rules_list = []
                for bad_word, good_word in sensitive_dict.items():
                    rules_list.append(f"将“{bad_word}”替换为“{good_word}”")
                
                if rules_list:
                    sensitive_rules = "5. **敏感词强制替换 (极度重要，关乎账号安全！)**：\n   在撰写文章时，遇到以下词汇必须强制替换为对应的安全词汇，绝不能在文章中出现左侧的敏感词：\n   - " + "\n   - ".join(rules_list)
        except Exception as e:
            logger.error(f"读取敏感词字典失败: {e}")

        article_prompt = f"""# Role: 资深专业竞彩分析师 / 体育媒体主编

## Profile:
你是一位拥有深厚足球底蕴和盘口逻辑分析能力的资深专家。你的文章面向具有一定看盘经验的竞彩玩家，他们需要的是**专业、严谨、客观且富有逻辑的深度前瞻**，而不是口语化的侃大山。

## Tone & Style (文风要求 - 极度重要！):
1. **专业严谨，用词考究**：抛弃“老铁、兄弟们”等轻浮口语。使用专业的体育新闻和盘口术语，如：“整体表现起伏不定”、“抢分效率稳定”、“优势与隐患并存”、“战意加持”、“让步高度”、“盘口逻辑”、“受热局面”、“平衡投注资金”。
2. **基本面深度剖析**：不要干巴巴列数字，要将积分榜形势、主客场战力差异、战意动力（如保级、德比恩怨、打破魔咒）以及伤病隐患融合成一段连贯的赛事背景分析。
3. **硬核盘口逻辑推演**：将亚指/欧指变化转化为“机构意图”。例如：“本场比赛机构开出主队X档的让步高度，这一盘口定位与两队的实力差距相匹配...从盘口逻辑来看，机构敢于开出深盘/浅盘，说明其对...持肯定/怀疑态度，意在平衡资金/利用题材制造悬念”。
4. **合规脱敏**：严禁使用“赌博、下注、买球、庄家”等词！请使用“数据、让步、指数、盘口逻辑”等中性词汇。
{sensitive_rules}

## Article Structure (文章结构要求 - 请严格遵循):
请生成一篇字数约 1000 字的专业前瞻文章，**必须严格使用标准的 Markdown 格式排版。请极其注意排版的美观性：每个大标题之间、每个自然段之间，必须严格保留一个空行（即使用 \n\n 换行），绝对不允许所有内容挤在一个自然段里！**

# 【标题】
(直接输出标题文本，不需要"标题："字样。标题应包含对阵双方和核心看点，如：英格兰东北德比，纽卡斯尔vs桑德兰百年恩怨，纽卡主场能否完成复仇！)

(此处必须空一行)

## 昨日回顾与今日展望
简短的一段话。虚构昨日战绩（如“昨日5场比赛拿下3场...”），然后一句话引出今天的重点赛事，表达信心。

(此处必须空一行)

## 基本面剖析
(必须分为至少两个独立的自然段，段落之间必须空一行)

(第一段：深入剖析主队当前的积分榜位置、战意诉求、近期状态及优隐患。**请将涉及到战意、核心优势的关键词使用 `<span style="color:red; font-weight:bold;">关键内容</span>` 这种HTML格式进行标红加粗！**)

(第二段：深入剖析客队的主客场表现差异，以及双方交锋历史、心理优势或复仇题材。**同样，请将客队的核心劣势或关键战绩标红加粗！**)

(此处必须空一行)

## 机构意图与官方指数逻辑推演
(必须分为清晰的段落，段落之间必须空一行)

(第一段：结合初盘和即时盘数据，分析机构给出的初始让步高度是否合理。**请将盘口的具体变化（如：主让半球升半一、水位下调）标红加粗！**)

(第二段：剖析后续数据的变化是在“顺势诱导受热方”，还是在“利用题材制造悬念，平衡投注资金”，并给出你对机构真实意图的判断。**请将最终的机构真实意图结论标红加粗！**)

(此处必须空一行)

## 比赛看法 (今日重点与扫盘)
(请严格按照以下紧凑的列表格式输出。首先给出今日重点分析的这场比赛的推荐。然后，从我提供的“今日其他可用的真实比赛列表”中挑选几场，形成一份完整的扫盘清单。**极度重要：每一场比赛的“竞彩”和“比分”后面的结果内容，都必须使用 `<span style="color:red; font-weight:bold;">` 标签进行标红加粗！**)

**001：[重点比赛主队] vs [重点比赛客队]**
- **赛事分析**：<span style="color:red; font-weight:bold;">[胜/平/负（可加注博某项）]</span>
- **比分**：<span style="color:red; font-weight:bold;">[X-X，X-X]</span>

(此处必须空一行)

**002：[其他真实比赛主队] vs [其他真实比赛客队]**
- **赛事分析**：<span style="color:red; font-weight:bold;">[让胜/让平 等]</span>
- **比分**：<span style="color:red; font-weight:bold;">[X-X，X-X]</span>

(以此类推)

(此处必须空一行)

<div style="font-size: 1.2em; font-weight: bold; text-align: center; margin: 20px 0;">
添加好友<br>
<span style="color: red;">朋友圈每日更新<span style="color: green;">二串一</span>，思路有变动，也会在圈内分享。</span><br>
<img src="https://files.mdnice.com/user/182547/8c40d7b1-7e6b-4896-bc09-52ed1a79764a.png" alt="添加老泊" style="max-width: 100%; height: auto; margin-top: 10px;">
</div>

(此处必须空一行)

> **免责声明**
> 本文所提供中国竞cai赛事分析文章，纯属兴趣而创作，数据及资讯来自中国竞cai官方网站。

---
请根据以下结构化的数据和原始AI报告，写出这篇极其专业的公众号推文！
"""
        logger.info(f"正在生成公众号推文：{match_data.get('home_team')} VS {match_data.get('away_team')}")
        
        # 构建其他可用比赛的简短信息，用于扫盘
        other_matches_info = "无"
        if all_matches:
            other_list = []
            for m in all_matches:
                # 排除当前正在重点分析的这场
                if m.get("match_num") != match_data.get("match_num"):
                    if m.get("llm_prediction") or m.get("all_predictions"):
                        # 获取最新的预测文本
                        pred_text = ""
                        if m.get("all_predictions"):
                            all_preds = m.get("all_predictions")
                            if 'final' in all_preds:
                                pred_text = all_preds['final']
                            elif 'pre_12h' in all_preds:
                                pred_text = all_preds['pre_12h']
                            elif 'pre_24h' in all_preds:
                                pred_text = all_preds['pre_24h']
                            else:
                                pred_text = list(all_preds.values())[-1]
                        else:
                            pred_text = m.get("llm_prediction")
                            
                        # 提取具体的推荐和比分
                        details = self.parse_prediction_details(pred_text)
                        rec = details['recommendation']
                        score = details['score']
                        other_list.append(f"- [{m.get('match_num')}] {m.get('league')} | {m.get('home_team')} VS {m.get('away_team')} -> 【必须严格使用此预测结果】: 竞彩推荐:<span style=\"color:red; font-weight:bold;\">{rec}</span>, 比分参考:<span style=\"color:red; font-weight:bold;\">{score}</span>")
                    else:
                        other_list.append(f"- [{m.get('match_num')}] {m.get('league')} | {m.get('home_team')} VS {m.get('away_team')} -> (暂无预测数据，请根据对阵自行分析)")
            if other_list:
                other_matches_info = "\n".join(other_list)
        
        user_content = f"【今日重点比赛信息】\n{self._format_match_data(match_data)}\n\n【原始AI深度分析报告】\n{prediction_text}\n\n【今日其他可用的真实比赛列表(用于扫盘)】\n{other_matches_info}\n\n请开始你的专业分析，并务必在文末附上包含重点赛事及上述真实比赛(最多选7场)的【比赛看法】扫盘列表！在写其他赛事的扫盘推荐时，**绝对不能改变上面提供的已有预测结果**！"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": article_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.7, # 稍微降低温度，确保逻辑严谨和格式稳定
                max_tokens=3500
            )
            
            article_text = response.choices[0].message.content
            
            # --- 强制后处理：暴力替换所有敏感词 ---
            try:
                if os.path.exists(dict_path):
                    with open(dict_path, 'r', encoding='utf-8') as f:
                        sensitive_dict = json.load(f)
                    
                    # 遍历字典，强制替换（注意：如果有互相包含的词，比如“让球”和“让球胜”，需要按长度降序排列，先替换长的）
                    # 按照键的长度从长到短排序，防止“让球胜”里的“让球”被提前替换导致剩余的“胜”无法匹配
                    sorted_keys = sorted(sensitive_dict.keys(), key=len, reverse=True)
                    for bad_word in sorted_keys:
                        good_word = sensitive_dict[bad_word]
                        # 执行替换
                        article_text = article_text.replace(bad_word, good_word)
            except Exception as e:
                logger.error(f"后处理替换敏感词失败: {e}")
            # -----------------------------------
            
            # 由于国内网络限制，使用国内能稳定访问的 Pexels/Unsplash 镜像或者使用基于文字生成的图片 API
            # 我们改回使用最稳定且在国内绝对不被墙的 Unsplash Source，并用英文关键词保证质量
            # 同时将文字水印交由用户在微信公众号后台自行添加，保证图片的绝对高清和可用性
            keyword = "football,stadium,match"
            import time
            timestamp = int(time.time() * 1000) # 使用毫秒级时间戳作为种子
            image_url = f"https://source.unsplash.com/1600x900/?{keyword}&sig={timestamp}"
            
            # 将图片 URL 单独返回，不在文章内嵌，由前端独立渲染
            return article_text, image_url
        except Exception as e:
            logger.error(f"生成推文失败: {e}")
            return f"生成推文失败: {e}", None

    def generate_post_mortem(self, date, accuracy_report):
        """
        V2: 基于程序化计算的准确率报告，让LLM只做洞察分析（不再自行判断对错）。
        accuracy_report: compute_accuracy_report() 的输出
        """
        logger.info(f"开始基于结构化数据生成 {date} 的深度复盘报告，窗口: {accuracy_report.get('batch_label', date)}，共 {accuracy_report['overall']['total']} 场")
        
        if not accuracy_report or accuracy_report["overall"]["total"] == 0:
            return "该日无已完成比赛或暂无准确率数据，无法生成复盘报告。"
        
        overall = accuracy_report["overall"]
        t = overall["total"]
        batch = accuracy_report.get("batch_label", date)
        rate_nspf = overall["correct_nspf"] / t * 100 if t > 0 else 0
        rate_spf = overall["correct_spf"] / t * 100 if t > 0 else 0
        
        league_lines = []
        for lg, st in sorted(accuracy_report["by_league"].items(), key=lambda x: x[1]["total"], reverse=True):
            if st["total"] > 0:
                acc = st["correct_nspf"] / st["total"] * 100
                league_lines.append(f"| {lg} | {st['total']}场 | {st['correct_nspf']}/{st['total']} | {acc:.0f}% |")
        league_table = "\n".join(league_lines) if league_lines else "无"
        
        handicap_lines = []
        for ht, st in sorted(accuracy_report["by_handicap"].items(), key=lambda x: x[1]["total"], reverse=True):
            if st["total"] > 0:
                acc = st["correct_nspf"] / st["total"] * 100
                handicap_lines.append(f"| {ht} | {st['total']}场 | {st['correct_nspf']}/{st['total']} | {acc:.0f}% |")
        handicap_table = "\n".join(handicap_lines) if handicap_lines else "无"
        
        errors = [m for m in accuracy_report["matches"] if not m["is_correct_nspf"]]
        
        error_lines = []
        for e in errors[:20]:
            reason_clean = e.get('reason', '无').replace('\n', ' ').replace('|', '｜')
            error_lines.append(
                f"| {e['match_num']} | {e['league']} | {e['home']} vs {e['away']} | "
                f"{e['actual_score']}({e['actual_nspf']}) | {e['pred_nspf']} | "
                f"初{e['asian_start']}→即{e['asian_live']} | {reason_clean} |"
            )
        error_table = "\n".join(error_lines) if error_lines else "（全部命中，无错误案例）"
        
        context = f"""## {batch} 预测准确率报告（程序化计算，数据无歧义）

### 整体统计
- 总场次: {t}
- **不让球命中率: {overall['correct_nspf']}/{t} = {rate_nspf:.1f}%**
- 让球命中率: {overall['correct_spf']}/{t} = {rate_spf:.1f}%
- 错误场次: {len(errors)}

### 按联赛准确率
| 联赛 | 场次 | 命中 | 准确率 |
|:---|:---|:---|:---|
{league_table}

### 按盘型准确率
| 盘型 | 场次 | 命中 | 准确率 |
|:---|:---|:---|:---|
{handicap_table}

### 错误案例清单（不让球预测与实际赛果不符）
| 编号 | 联赛 | 对阵 | 赛果 | AI预测 | 盘口变化 | 预测逻辑简述 |
|:---|:---|:---|:---|:---|:---|:---|
{error_table}
"""
        
        prompt = f"""你是竞彩风控分析师。以下数据已经由程序精确计算，请仅基于这些数据进行分析。

{context}

你的任务：
1. **识别错误集中规律**：哪类盘型或哪些联赛错误率最高？这些比赛中是否存在共性？
2. **深度盘赔异动分析（核心）**：重点关注错误案例中的“初盘→即时盘”变化。如果模型基于升盘升水、退盘降水等盘口赔率变动做出了判断但最终错误，请深度剖析当时的判断逻辑是否出现了偏差（例如：将真实的实力调整误判为诱盘，或将机构的真实阻力误判为造热）。
3. **分析错误根因**：结合盘赔异动分析，找出预测共同失败的模式。
4. **提出优化建议（最多3条）**：基于上述分析，提出具体的预测模型优化建议。

严格约束：
- 严禁捏造任何不在此报告中的数据、比分或预测内容
- 胜=主队胜、负=主队负。严禁将"平/胜"说成"看好客队"
- 如果某场错误表显示预测为"胜(60%)/平(40%)"而赛果是"负"，你只能说"模型预测主队不败但主队输了"
- 输出用Markdown，分为"错误集中规律"、"根因分析"、"优化建议"三部分
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是数据驱动的竞彩风控分析师。只基于提供的数据进行分析，严禁编造任何不在数据中的信息。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=3000
            )
            review_text = response.choices[0].message.content
            
            batch = accuracy_report.get("batch_label", date)
            header = f"""## 📊 {batch} 准确率统计

| 维度 | 数值 |
|:---|:---|
| 总场次 | {t} |
| 不让球命中率 | {overall['correct_nspf']}/{t} = {rate_nspf:.1f}% |
| 让球命中率 | {overall['correct_spf']}/{t} = {rate_spf:.1f}% |
| 错误场次 | {len(errors)} |

---
## 🤖 AI辅助洞察

"""
            return header + review_text
        except Exception as e:
            logger.error(f"调用LLM生成复盘报告异常: {e}")
            return "生成复盘报告失败，请稍后重试。"

    @staticmethod
    def validate_review(review_text, accuracy_report):
        """
        校验LLM生成的复盘报告是否存在明显事实错误。
        返回: (is_valid: bool, warnings: list)
        """
        warnings = []
        import re
        
        if not review_text or not accuracy_report:
            return True, []
        
        # 校验1: 准确率数字一致性
        t = accuracy_report["overall"]["total"]
        correct_nspf = accuracy_report["overall"]["correct_nspf"]
        expected_rate = f"{correct_nspf}/{t}"
        
        numbers_in_review = re.findall(r'(\d+)/(\d+)', review_text)
        for n1, n2 in numbers_in_review:
            if n1 == str(correct_nspf) and n2 == str(t):
                break
        else:
            warnings.append("准确率数字不在报告中")
        
        # 校验2: "主客颠倒"检测
        for pattern in [r'看好客队', r'客队不败', r'客胜.{0,5}预测.{0,10}平.{0,3}胜',
                       r'预测.*?平.{0,3}胜.{0,10}客队']:
            if re.search(pattern, review_text):
                warnings.append("检测到可能的'主客颠倒'表述（将主队不败描述为客队有利）")
                break
        
        # 校验3: 错误场次数一致性
        errors = [m for m in accuracy_report["matches"] if not m["is_correct_nspf"]]
        match_count = re.findall(r'(\d+)\s*场.*错误|错误.*?(\d+)\s*场', review_text)
        
        return len(warnings) == 0, warnings

    def predict(self, match_data, period=None, total_matches_count=None, is_sfc=False, other_matches_context=None):
        """
        调用 LLM 进行预测，支持时间段标识
        基于 Multi-Agent 工作流的 V3 预测引擎。
        包含三步：基本面分析 -> 盘口推演 -> 风控裁判最终裁决。
        """
        # 自动判断时间段
        if period is None:
            period = self._determine_prediction_period(match_data)
            
        try:
            # 1. 格式化数据并提取盘口标签
            formatted_data = self._format_match_data(match_data, is_sfc)
            handicap_label = self._classify_handicap(match_data.get('odds', {}).get('rangqiu', '0'), match_data.get('asian_odds', {}))
            
            # 2. 动态组装规则
            dynamic_rules = self._build_dynamic_rules(match_data, handicap_label)
            
            # ==========================================
            # Agent A: 基本面专员 (仅看基本面数据)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent A 正在分析基本面...")
            agent_a_data = self._extract_fundamentals(match_data)
            agent_a_response = self.client.chat.completions.create(
                model=os.getenv('LLM_MODEL', 'ep-20250212200331-52ndx'),
                messages=[
                    {"role": "system", "content": AGENT_A_PROMPT},
                    {"role": "user", "content": f"请分析以下比赛的基本面：\n{agent_a_data}"}
                ],
                temperature=0.3
            )
            agent_a_conclusion = agent_a_response.choices[0].message.content
            
            # ==========================================
            # Agent B: 盘口推演专员 (仅看盘口与预警数据)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent B 正在推演盘口意图...")
            agent_b_data = self._extract_odds_data(match_data)
            agent_b_response = self.client.chat.completions.create(
                model=os.getenv('LLM_MODEL', 'ep-20250212200331-52ndx'),
                messages=[
                    {"role": "system", "content": AGENT_B_PROMPT},
                    {"role": "user", "content": f"请推演以下比赛的机构盘口意图：\n{agent_b_data}"}
                ],
                temperature=0.4
            )
            agent_b_conclusion = agent_b_response.choices[0].message.content
            
            # ==========================================
            # Agent C: 风控裁判长 (整合输出)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent C 正在进行最终风控裁决...")
            final_prompt = f"""
{AGENT_C_PROMPT}

### 🔴 动态风控铁律 (本场比赛必须遵守)
{dynamic_rules}

---
### 比赛原始数据参考
{formatted_data}

---
### 专员报告
**【基本面专员报告】**：
{agent_a_conclusion}

**【盘口专员报告】**：
{agent_b_conclusion}

请根据以上报告和风控铁律，输出最终预测。
"""
            agent_c_response = self.client.chat.completions.create(
                model=os.getenv('LLM_MODEL', 'ep-20250212200331-52ndx'),
                messages=[
                    {"role": "user", "content": final_prompt}
                ],
                temperature=0.2 # 裁判长需要极其冷静客观
            )
            
            result = agent_c_response.choices[0].message.content
            logger.info(f"预测成功返回！ [时间段: {period}]")
            return result, period
            
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            return f"预测失败: {e}", period

    def _extract_fundamentals(self, match_data):
        """为 Agent A 提取纯基本面数据"""
        info = f"- 赛事信息：{match_data.get('league')} | {match_data.get('home_team')} VS {match_data.get('away_team')}\n"
        recent = match_data.get('recent_form', {})
        if recent.get('standings'):
            info += f"- 联赛积分与排名：{recent.get('standings')}\n"
        info += f"- 主队近期战绩：{recent.get('home', '暂无')}\n"
        info += f"- 客队近期战绩：{recent.get('away', '暂无')}\n"
        info += f"- 交锋记录：{match_data.get('h2h_summary', '暂无')}\n"
        if recent.get('injuries') and recent.get('injuries') != "暂无详细伤停数据":
            info += f"- 伤停与阵容：{recent.get('injuries')}\n"
            
        adv_stats = match_data.get('advanced_stats', {})
        home_adv = adv_stats.get('home', {})
        away_adv = adv_stats.get('away', {})
        info += f"- 主队场均射门 {home_adv.get('avg_shots', '未知')}, 场均射正 {home_adv.get('avg_shots_on_target', '未知')}\n"
        info += f"- 客队场均射门 {away_adv.get('avg_shots', '未知')}, 场均射正 {away_adv.get('avg_shots_on_target', '未知')}\n"
        return info

    def _extract_odds_data(self, match_data):
        """为 Agent B 提取纯盘口和预警数据"""
        info = ""
        odds = match_data.get('odds', {})
        if odds.get('nspf'):
            info += f"- 竞彩不让球赔率：{odds.get('nspf', [])}\n"
        if odds.get('spf'):
            info += f"- 竞彩让球({odds.get('rangqiu')})赔率：{odds.get('spf', [])}\n"
            
        asian = match_data.get('asian_odds', {})
        if 'macau' in asian:
            info += f"- 澳门亚指：初盘 [{asian['macau'].get('start')}] -> 即时盘 [{asian['macau'].get('live')}]\n"
            
        # 加入量化预警
        deep_water = self._detect_deep_water_trap(asian)
        if deep_water: info += f"- 🚨 超深盘死水预警：{deep_water}\n"
        
        half_ball = self._detect_half_ball_trap(asian, odds)
        if half_ball: info += f"- 🔴 半球生死盘预警：{half_ball}\n"
        
        divergence = self._detect_handicap_water_divergence(asian)
        if divergence: info += f"- 🔴 盘水背离预警：{divergence}\n"
        
        euro_asian = self._detect_euro_asian_divergence(odds, asian)
        if euro_asian: info += f"- 🚨 欧亚背离量化预警：{euro_asian}\n"
        
        return info

    def _determine_prediction_period(self, match_data):
        """
        根据比赛时间判断预测时间段
        :return: 'pre_24h', 'pre_12h', 'final'
        """
        try:
            match_time_str = match_data.get("match_time")
            if not match_time_str:
                return "pre_24h"
                
            # 解析比赛时间
            match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
            now = datetime.now()
            time_diff = match_time - now
            
            # 判断时间段
            if time_diff.total_seconds() > 24 * 3600:  # 大于24小时
                return "pre_24h"
            elif time_diff.total_seconds() > 12 * 3600:  # 12-24小时
                return "pre_12h"
            else:  # 小于12小时
                return "final"
                
        except Exception as e:
            logger.warning(f"判断时间段失败: {e}, 默认使用 pre_24h")
            return "pre_24h"

    def generate_parlays(self, summary_data):
        """
        基于当日预测结果，生成五个不同倍率的实战串关方案（引入 CoT 强制思维链与模块化 Prompt）
        """
        cross_match_warning = ""
        if len(summary_data) <= 3:
            cross_match_warning = f"""
🚨 **【高危预警：极端赛程交叉盘风险】** 🚨
注意：今天汇总数据中一共只有 {len(summary_data)} 场比赛！由于赛事过少，允许你**删减方案数量**（如只出3个方案），但必须在开头说明。
根据国内主任操盘的经典规律，当单日比赛极少时极易触发“交叉盘”专杀剧本。
**在此极端情况下，必须绝对遵守以下风控原则：**
- **严禁双胆双热**：绝对不允许将两场基本面大热的强队串在一起！
- **强制防冷/交叉组合**：稳健单中必须至少包含一场防冷双选，或者采用“一正一反”的交叉策略。
- **方案提示**：在方案的“核心组合逻辑”中，必须向用户明确提示今天的“交叉盘”高危风险。
"""

        prompt = f"""# Role: 资深竞彩操盘手 / 实战串关专家

## Profile & Task
你是一位精通竞彩风控和赔率计算的实战专家。请基于我提供的【今日赛事预测汇总数据】，挑选合适的比赛组合出**五个不同类型的实战方案**。如果赛事过少，允许你按需删减方案数量并在开头说明。

{cross_match_warning}

## 🔴 绝对铁律 (Hard Constraints - 触犯即判负)
1. **[跨日禁令]**：每个方案内的所有比赛**必须属于同一个比赛日**（如“周五001”和“周六002”绝对不能串在一起）。
2. **[一致性禁令]**：你在方案中推荐的任何赛果方向（胜/平/负/让负等），**必须与输入数据中该场的「[结论]」绝对一致**！例如结论写了不让球推荐“平/负”，你绝不能在串关里推“胜”。如果该场某个玩法结论标注为“未推荐”，则严禁使用该玩法。
3. **[防堆砌禁令]**：绝对禁止在一个方案中盲目堆砌同一类型的冷门（如博4个平局或3场让负）。每一场冷门必须从其「核心理由」中提取独立的爆发逻辑。
4. **[有理有据]**：挑选的每一场必须有“核心理由”支撑，禁止脱离基本面瞎选。避开大热必死的比赛。
5. **[风险隔离禁令] (极度重要)**：同一场比赛**最多只能在所有方案中出现 2 次**！作为高倍单（方案四、五）博冷胆材的比赛，**绝对不能**与稳健单（方案二）的赛事重合，防止一场爆冷导致全盘覆没。
6. **[合法双选边界]**：实战终端无法打出跨玩法双选。你的任何【双选】必须局限于**同一个玩法内部**（例如：只双选不让球的平+负，或只双选进球数的2+3）。绝对禁止“胜+让负”这种无法出票的幽灵组合。

## 📊 方案配置表 (Strategy Config)
| 方案名称 | 场次要求 | 玩法要求 | 容错/防冷策略 | 目标净回报倍率 |
| :--- | :--- | :--- | :--- | :--- |
| **方案一：精选单关** | 1~3场(各自独立) | **优先使用【进球数双拼】或【半全场】**。若选胜负，需提示用户"若非官方单关请串其他极低赔率比赛"。 | **进球数双拼**：至少包含1场比赛给出两个进球数的单关组合(如单博2球或3球)。 | 单场赔率 > 1.8 |
| **方案二：稳健回血** | 2场串关 | 推荐置信度60~80%赛事。 | 最多只能包含1场双选。优先避开极热大盘。 | **2.5 ~ 5 倍** |
| **方案三：进阶盈利** | 2~3场串关(2串1优先) | 胜平负/让球/进球数/半全场均可。 | **进球数强制双选**：若本方案选了进球数玩法，必须双选(如"2,3球")，严禁单选！ | **5 ~ 10 倍** |
| **方案四：以小博大** | 严格2场串关 | 博冷平局 / 博下盘让负 / 半全场高赔 | 严禁为了凑倍数而增加场次，纯粹用高赔选项来博。 | **10 倍以上** |
| **方案五：梦想博冷** | 3~4场串关(3串1优先) | **结构强制**：必须采用"稳胆(置信度>70%)+冷门"混搭模式。 | **禁止纯冷门堆砌**，必须多样化(如1个平局+1个深盘让负+1个高赔半全场)。必须说明单场爆冷理由。 | **20 倍以上** |

## 🧮 赔率计算引擎 (CoT Template - 强制输出格式)
在输出每个方案时，必须严格遵守以下计算公式，并**完全套用 `<赔率推演>` 模板**，严禁编造赔率！
* **赔率取值**：从输入数据的「[赔率]」中提取对应选项的真实SP值。
* **[豁免声明]**：由于进球数和比分玩法的真实 SP 值未提供，若方案中包含这两种玩法，**允许在推演中使用行业平均估值（如进球数2/3球按3.5估算，半全场按6.0估算，比分按8.0估算），但必须在赔率旁标注 `(估算SP)`**。胜平负和让球玩法依然**严禁估算**，必须用真实数据。
* **注数** = 各场选项数量相乘 (如：单选×双选 = 2注)。
* **净回报** = (所有场次最低赔率相乘 ÷ 注数) ~ (所有场次最高赔率相乘 ÷ 注数)

【强制输出模板】(每个方案都必须包含)：
### 方案X：[方案名称] (预期净回报：X ~ Y倍)
* **[赛事编号]** [对阵] | **推荐：[具体玩法选项]**
* **[赛事编号]** [对阵] | **推荐：[具体玩法选项]**
> 💡 **核心组合逻辑**：[一句话说明选场依据，指出哪个是胆，哪个是博]
> 🧮 **赔率推演**：
> - [赛事编号] (单选X): 赔率 2.0
> - [赛事编号] (双选Y/Z): 赔率 3.1 / 1.5
> - 注数计算: 1 × 2 = 2 注
> - 理论最低赔率: 2.0 × 1.5 = 3.0
> - 理论最高赔率: 2.0 × 3.1 = 6.2
> - 真实净回报: 最低 1.5 倍 ~ 最高 3.1 倍

---
以下是今日赛事的预测汇总数据：
{summary_data}
"""
        # 将 summary_data 格式化为精准文本，减少不必要的干扰信息
        match_info_lines = []
        for data in summary_data:
            line = f"[{data.get('编号')}] {data.get('赛事')} | {data.get('主队')} VS {data.get('客队')}\n"
            
            # 不让球数据处理
            nspf = data.get('竞彩推荐(不让球)') or data.get('竞彩推荐')
            nspf_odds = data.get('不让球赔率(胜/平/负)', [])
            if nspf and nspf != '无':
                line += f"  - [结论] 竞彩推荐(不让球): {nspf}\n"
                if nspf_odds and len(nspf_odds) == 3:
                    line += f"  - [赔率] 不让球(胜/平/负): {nspf_odds[0]} / {nspf_odds[1]} / {nspf_odds[2]}\n"
            else:
                line += f"  - [结论] 竞彩推荐(不让球): (未推荐，严禁在方案中选择此项)\n"

            # 让球数据处理
            rq = data.get('竞彩让球推荐')
            rq_val = data.get('让球数', '0')
            spf_odds = data.get('让球赔率(胜/平/负)', [])
            if rq and rq != '无':
                line += f"  - [结论] 竞彩让球({rq_val})推荐: {rq}\n"
                if spf_odds and len(spf_odds) == 3:
                    line += f"  - [赔率] 让球(胜/平/负): {spf_odds[0]} / {spf_odds[1]} / {spf_odds[2]}\n"
            else:
                line += f"  - [结论] 竞彩让球推荐: (未推荐，严禁在方案中选择此项)\n"

            # 进球数与比分处理
            goals_ref = data.get('AI预测进球数') if data.get('AI预测进球数') and data.get('AI预测进球数') != '无' else data.get('进球数参考', '无')
            line += f"  - [结论] 进球数参考: {goals_ref}\n"
            line += f"  - [结论] 比分参考: {data.get('比分参考')}\n"
            
            # 置信度与理由
            line += f"  - 置信度: {data.get('置信度')}\n"
            line += f"  - 核心理由: {data.get('基础理由')}\n"
            match_info_lines.append(line)
            
        match_data_text = "\n".join(match_info_lines)
        final_prompt = prompt.replace("{summary_data}", match_data_text)

        try:
            # 使用配置的模型 生成串关
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个资深的竞彩操盘手，精通实战串关。"},
                    {"role": "user", "content": final_prompt}
                ],
                temperature=0.7,
                max_tokens=8000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"调用 LLM 生成串关方案失败: {e}")
            return f"❌ 生成串关方案失败，请检查 API 配置或网络连接。错误信息: {e}"

    def compare_parlays(self, parlay_1, parlay_2):
        """
        对比两次不同的串关方案，分析其优劣
        """
        prompt = f"""# Role: 资深竞彩风控总监

## Task:
我这里有两次由AI生成的不同竞彩串关方案。请你作为风控总监，客观地对比这两次方案的不同之处，并深入分析它们的优劣势。

## Input:
【方案 A (前次生成)】
{parlay_1}

【方案 B (最新生成)】
{parlay_2}

## Output Requirements:
请使用美观的 Markdown 格式输出，包含以下结构：
1. **🎯 选场差异分析**：对比两次方案在比赛选择上的不同偏好（例如：A方案偏好早场，B方案偏好某特定联赛；或者A方案挑了某场冷门，B方案避开了）。
2. **⚖️ 风险与回报评估**：对比两次方案在“稳健单”、“进阶单”、“高倍单”上的赔率和容错率差异。哪个方案更容易落地？哪个方案的搏冷更具性价比？
3. **💡 操盘手最终建议**：给出你作为风控总监的最终建议。比如：建议综合A的稳健单和B的高倍单，或者指出某一场比赛在两次方案中都被选中，说明是超级稳胆。

请直接输出分析内容，语言专业严谨。
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是资深竞彩风控总监，负责评估不同投注方案的风险与回报。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"调用 LLM 对比串关方案失败: {e}")
            return f"❌ 对比分析失败: {e}"

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", ".env"))
    
    # 测试一下本地缓存的数据
    try:
        with open("data/today_matches.json", "r", encoding="utf-8") as f:
            matches = json.load(f)
            if matches:
                predictor = LLMPredictor()
                print("========================================")
                print(predictor._format_match_data(matches[0]))
                print("========================================")
                res, period = predictor.predict(matches[0], total_matches_count=len(matches))
                print(res)
    except Exception as e:
        print(f"测试出错: {e}")
