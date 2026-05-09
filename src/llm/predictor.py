import os
import re
import json
import urllib.parse
import itertools
from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 动态规则引擎
import simpleeval

# 引入动态规则模块
from .rules import P0_CORE_RULES, HANDICAP_RULES, DYNAMIC_CHANGE_RULES, HOT_MONEY_RULES
from .rules import AGENT_A_PROMPT, AGENT_B_PROMPT, AGENT_C_PROMPT
from src.utils.rule_registry import normalize_arbitration_rule_action

class LLMPredictor:
    def __init__(self):
        # 动态计算 .env 文件的绝对路径
        base_dir = self._get_project_base_dir()
        env_path = os.path.join(base_dir, "config", ".env")
        load_dotenv(env_path)
        
        api_key = os.getenv("LLM_API_KEY")
        api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o")

        api_base = api_base.rstrip("/")
        if not api_base.endswith("/v1"):
            api_base = f"{api_base}/v1"
        
        if not api_key:
            logger.error("未找到 LLM_API_KEY，请检查 .env 文件")
            raise ValueError("LLM_API_KEY is not set")
            
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base
        )

    @staticmethod
    def _get_project_base_dir():
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
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
        rules.append(HOT_MONEY_RULES)
        
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

        # --- 结构化量化伤停数据 ---
        injuries_detailed = match.get('injuries_detailed', {})
        if injuries_detailed:
            injuries_text = injuries_detailed.get('injuries_text', '')
            if injuries_text:
                parsed = self._parse_leisu_injuries(injuries_text)
                if parsed["valid"]:
                    structured = self._format_structured_leisu_injuries(match)
                    info += f"  - 🔴 **量化伤停影响**：核心缺阵约 {parsed['core_count']} 人\n"
                    if structured["valid"]:
                        for line in structured["text"].split("\n"):
                            info += f"  - 结构化伤停：{line}\n"
                    info += f"  - 伤停明细：{parsed['text'][:600]}\n"
                else:
                    info += f"  - ⚠️ 伤停明细疑似乱码/无效，已跳过量化（原因：{parsed['reason']}）\n"
                    if parsed["text"]:
                        info += f"  - 原始伤停片段：{parsed['text'][:180]}\n"

        # --- 进球分布 ---
        goal_dist = match.get('goal_distribution', [])
        if goal_dist and isinstance(goal_dist, list):
            info += f"  - 进球时间分布：{goal_dist[:18]}\n"

        # --- 积分排名 ---
        standings_info = match.get('standings_info', [])
        if standings_info:
            info += f"  - 联赛排名：{standings_info}\n"

        # --- 历史交锋 ---
        h2h_leisu = match.get('h2h_leisu', [])
        if h2h_leisu:
            info += f"  - 历史交锋比分：{h2h_leisu[:8]}\n"

        # --- 近期战绩 ---
        recent_leisu = match.get('recent_leisu', [])
        if recent_leisu:
            info += f"  - 近期战绩比分：{recent_leisu[:10]}\n"
        for line in self._format_leisu_intelligence_block(match, prefix="  - "):
            info += f"{line}\n"
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

        market_anchor = self._build_market_anchor_summary(match)
        info += f"  - 🔎 市场锚点定义：{market_anchor['text']}\n"
            
        # 盘赔异动检测 (结构化摘要)
        asian_change = self._detect_odds_change(asian)
        if asian_change:
            info += f"  - 盘赔异动摘要：{asian_change}\n"

        micro_signals = self._analyze_micro_market_signals(match.get("odds", {}), asian, league, euro_odds=match.get('europe_odds', []))
        if micro_signals:
            info += f"  - 🧩 盘赔微观信号：\n"
            for line in micro_signals.split("\n"):
                if line.strip():
                    info += f"    - {self._format_signal_with_prediction_bias(line, asian)}\n"
        
        # 盘型标注（帮助LLM快速定位适用规则）
        handicap_label = self._classify_handicap(odds.get('rangqiu','0'), asian)
        if handicap_label:
            info += f"  - 亚指盘型：{handicap_label}\n"
        
        # 1. 🚨 超深盘死水预警 (针对两球以上盘口)
        deep_water_warning = self._detect_deep_water_trap(asian)
        if deep_water_warning:
            info += f"  - 🚨 **超深盘死水预警**：{self._format_signal_with_prediction_bias(deep_water_warning, asian)}\n"
            
        # 2. 🔴 半球生死盘异动预警
        half_ball_warning = self._detect_half_ball_trap(asian, odds)
        if half_ball_warning:
            info += f"  - 🔴 **半球生死盘预警**：{self._format_signal_with_prediction_bias(half_ball_warning, asian)}\n"
            
        # 3. ⚠️ 平手盘水位僵持检测
        flat_water_warning = self._detect_flat_water_static(asian)
        if flat_water_warning:
            info += f"  - ⚠️ **平手盘水位僵持预警**：{self._format_signal_with_prediction_bias(flat_water_warning, asian)}\n"
        
        # 4. 🚨 赔率方向矛盾检测
        odds_conflict = self._detect_odds_conflict(odds, asian, match.get('europe_odds', []))
        if odds_conflict:
            info += f"  - 🚨 **赔率方向矛盾预警**：{self._format_signal_with_prediction_bias(odds_conflict, asian)}\n"
        
        # 5. 🔴 盘水背离检测（升盘+升水诱上信号）
        divergence_warning = self._detect_handicap_water_divergence(asian)
        if divergence_warning:
            info += f"  - 🔴 **盘水背离预警（让球方虚热/诱上信号）**：{self._format_signal_with_prediction_bias(divergence_warning, asian)}\n"
            
        # 6. 🔴 浅盘临场升水诱下预警 (04-30复盘新增)
        shallow_water_warning = self._detect_shallow_water_trap(asian, odds)
        if shallow_water_warning:
            info += f"  - 🔴 **浅盘升水诱下预警**：{self._format_signal_with_prediction_bias(shallow_water_warning, asian)}\n"
            
        # 7. 🚨 欧亚背离量化预警 (V3架构新增)
        euro_asian_warning = self._detect_euro_asian_divergence(odds, asian, match.get('europe_odds', []))
        if euro_asian_warning:
            info += f"  - 🚨 **欧亚背离量化预警**：{self._format_signal_with_prediction_bias(euro_asian_warning, asian)}\n"

        # 8. 🔴 浅盘示弱诱下/阻上预警 (05-01复盘新增)
        shallow_showweak_warning = self._detect_shallow_showweak_induce_down(asian)
        if shallow_showweak_warning:
            info += f"  - 🔴 **浅盘示弱诱下预警**：{self._format_signal_with_prediction_bias(shallow_showweak_warning, asian)}\n"
            
        return info

    def _parse_leisu_injuries(self, injuries_text):
        text = re.sub(r"\s+", " ", str(injuries_text or "")).strip()
        if not text:
            return {"valid": False, "reason": "空文本", "core_count": None, "text": ""}

        # 常见乱码/转码异常特征（UTF-8/GBK 误解码）
        mojibake_chars = set("鏉鎴寮闆銆鈥锛锟涓浠绾鐢缁鍒娉璧浣鍏鑳")
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        mojibake_count = sum(1 for ch in cjk_chars if ch in mojibake_chars)
        mojibake_ratio = (mojibake_count / len(cjk_chars)) if cjk_chars else 0.0

        if "锟斤拷" in text or "�" in text:
            return {"valid": False, "reason": "出现替换字符", "core_count": None, "text": text}
        if mojibake_ratio >= 0.22 and len(cjk_chars) >= 20:
            return {"valid": False, "reason": "疑似转码乱码", "core_count": None, "text": text}

        # 仅当明细里出现明确伤停词时才量化，防止“0人”误导
        meaningful_keywords = (
            "伤病", "停赛", "受伤", "归队", "缺阵", "伤停", "球员", "位置", "原因",
            "肌肉", "韧带", "骨折", "跟腱", "膝", "踝", "赛季报销", "暂无数据"
        )
        if not any(k in text for k in meaningful_keywords):
            return {"valid": False, "reason": "缺少可识别伤停关键词", "core_count": None, "text": text}

        core_count = len(re.findall(r'(?:跟腱|肌肉|韧带|膝|踝|骨折|重伤|赛季报销)', text))
        return {"valid": True, "reason": "", "core_count": core_count, "text": text}

    def _team_name_matches(self, raw_header, team_name):
        raw_header = (raw_header or "").strip()
        team_name = (team_name or "").strip()
        if not raw_header or not team_name:
            return False
        if team_name in raw_header or raw_header in team_name:
            return True
        if len(team_name) >= 2 and team_name[:2] in raw_header:
            return True
        tokens = [tok for tok in re.split(r"[\s·\-]+", team_name) if tok]
        return any(len(tok) >= 2 and tok in raw_header for tok in tokens)

    def _extract_reason_text(self, line):
        line = re.sub(r"\s+", " ", str(line or "")).strip(" -\t")
        if not line:
            return ""
        reason_keywords = (
            "肌肉", "挫伤", "韧带", "关节", "骨折", "扭伤", "拉伤", "跟腱", "膝", "踝",
            "大腿", "臀", "髋", "腹股沟", "伤病", "受伤", "停赛", "轮休", "缺阵", "赛季报销"
        )
        if any(k in line for k in reason_keywords):
            line = re.sub(r"^(未知|后卫|中场|前锋|门将)\s+", "", line)
            return line
        return ""

    def _summarize_leisu_injuries(self, injuries_text, home_team="", away_team=""):
        parsed = self._parse_leisu_injuries(injuries_text)
        if not parsed["valid"]:
            return {"valid": False, "reason": parsed["reason"], "teams": [], "text": parsed["text"]}

        raw_lines = [ln.strip() for ln in str(injuries_text or "").splitlines()]
        lines = [ln for ln in raw_lines if ln]
        ignore_headers = {"球员", "位置", "原因", "开始时间", "归队时间", "影响场数", "伤病", "停赛"}
        teams = []
        current_team = None
        current_section = None
        pending_player = None

        def ensure_team(team_label):
            nonlocal current_team
            for team in teams:
                if team["team"] == team_label:
                    current_team = team
                    return
            team = {"team": team_label, "injuries": [], "suspensions": [], "core_count": 0}
            teams.append(team)
            current_team = team

        def add_entry(player_name, reason_text, section_name):
            nonlocal pending_player
            if not current_team or not player_name:
                pending_player = None
                return
            section_key = "suspensions" if section_name == "停赛" else "injuries"
            current_team[section_key].append({"player": player_name, "reason": reason_text or section_name})
            if section_key == "injuries" and re.search(r'(?:跟腱|肌肉|韧带|膝|踝|骨折|重伤|赛季报销|大腿|髋|关节)', reason_text or ""):
                current_team["core_count"] += 1
            pending_player = None

        for line in lines:
            normalized = re.sub(r"\s+", " ", line).strip()
            if not normalized:
                continue

            if self._team_name_matches(normalized, home_team):
                ensure_team(home_team or normalized)
                current_section = None
                pending_player = None
                continue
            if self._team_name_matches(normalized, away_team):
                ensure_team(away_team or normalized)
                current_section = None
                pending_player = None
                continue

            if normalized in ("伤病", "停赛"):
                current_section = normalized
                pending_player = None
                continue

            if normalized in ignore_headers or normalized.replace(" ", "") == "球员位置原因开始时间归队时间影响场数":
                continue
            if normalized in ("-", "--"):
                continue
            if not current_team or not current_section:
                continue

            reason_text = self._extract_reason_text(normalized)
            if pending_player and reason_text:
                add_entry(pending_player, reason_text, current_section)
                continue

            if len(normalized) <= 20 and not any(ch.isdigit() for ch in normalized) and not reason_text:
                pending_player = normalized
                continue

            if pending_player and current_section == "停赛":
                add_entry(pending_player, normalized, current_section)

        structured_teams = [team for team in teams if team["injuries"] or team["suspensions"]]
        return {"valid": bool(structured_teams), "reason": "" if structured_teams else "未解析出结构化条目", "teams": structured_teams, "text": parsed["text"]}

    def _format_structured_leisu_injuries(self, match_data):
        injuries_text = (match_data.get("injuries_detailed") or {}).get("injuries_text", "")
        summary = self._summarize_leisu_injuries(
            injuries_text,
            home_team=match_data.get("home_team", ""),
            away_team=match_data.get("away_team", ""),
        )
        if not summary["valid"]:
            return {"valid": False, "text": "", "reason": summary["reason"]}

        lines = []
        for team in summary["teams"]:
            injury_desc = "、".join([f"{item['player']}({item['reason']})" for item in team["injuries"][:6]]) or "无明确伤病"
            suspension_desc = "、".join([f"{item['player']}({item['reason']})" for item in team["suspensions"][:4]])
            line = f"{team['team']}：伤病{len(team['injuries'])}人"
            if team["core_count"] > 0:
                line += f"，核心伤停约{team['core_count']}人"
            line += f"；明细 {injury_desc}"
            if suspension_desc:
                line += f"；停赛/轮休 {suspension_desc}"
            lines.append(line)
        return {"valid": True, "text": "\n".join(lines), "reason": ""}

    @staticmethod
    def _format_leisu_intelligence_block(match_data, prefix="- "):
        intel = match_data.get("leisu_intelligence") or {}
        home = intel.get("home") or {}
        away = intel.get("away") or {}
        neutral = intel.get("neutral") or []
        if not any([home.get("pros"), home.get("cons"), away.get("pros"), away.get("cons"), neutral]):
            return []

        home_label = intel.get("home_team") or match_data.get("home_team", "主队")
        away_label = intel.get("away_team") or match_data.get("away_team", "客队")
        lines = []
        if home.get("pros"):
            lines.append(f"{prefix}情报要点-主队有利：{home_label} -> {'；'.join(home['pros'][:3])}")
        if home.get("cons"):
            lines.append(f"{prefix}情报要点-主队不利：{home_label} -> {'；'.join(home['cons'][:3])}")
        if away.get("pros"):
            lines.append(f"{prefix}情报要点-客队有利：{away_label} -> {'；'.join(away['pros'][:3])}")
        if away.get("cons"):
            lines.append(f"{prefix}情报要点-客队不利：{away_label} -> {'；'.join(away['cons'][:3])}")
        if neutral:
            lines.append(f"{prefix}情报要点-中立因素：{'；'.join(neutral[:2])}")
        return lines

    @classmethod
    def _build_leisu_intel_anchor_hint(cls, match_data):
        intel = match_data.get("leisu_intelligence") or {}
        if not intel:
            return "暂无"

        anchor = cls._build_market_anchor_summary(match_data)
        asian_side = anchor.get("asian", {}).get("side")
        euro_side = anchor.get("euro", {}).get("side")

        def side_label(side):
            if side == "home":
                return "主队"
            if side == "away":
                return "客队"
            return "未明确"

        hints = [f"- 情报归属提示：亚赔让球方={side_label(asian_side)}；欧赔实力方={side_label(euro_side)}。"]
        hints.append("- 盘赔解释时，必须明确哪些情报是在支持让球方，哪些情报是在支持受让方。")
        hints.append("- 若某条情报更适合解释欧赔为何长期保护某一方，请明确标为“支持欧赔实力方”。")
        hints.append("- 若某条情报只是被机构用来放大利空、制造热度或控热，请明确标为“机构借题发挥/借情报控热”。")
        return "\n".join(hints)

    @staticmethod
    def _detect_deep_water_trap(asian):
        """
        检测超深盘（1.75及以上）的死水陷阱（04-29复盘新增）。
        超深盘下若水位毫无波动，往往是机构张网以待诱导让球方，极易出现受让方方向冷门。
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
            giving_side = "客队" if handicap_raw.startswith('受') else "主队"
            upset_hint = "胜/平" if giving_side == "客队" else "平/负"
            return (f"初盘[{handicap_raw}]为超深盘，但临场水位几乎毫无波动（死水一潭）。"
                    "超深盘不降水规避风险，说明机构在利用深盘诱导买入让球方，"
                    f"**这是极其典型的受让方方向冷门温床，不让球玩法需重点覆盖 {upset_hint}！**")
        return ""

    @staticmethod
    def _detect_half_ball_trap(asian, odds):
        """
        检测半球生死盘的水位异动与资金流向（04-29复盘新增）。
        半球盘赢球即赢盘，打平即全输。
        1. 升水诱导：半球盘让球方水位异常升高 -> 大众资金追捧让球方，机构顺势提升赔付（诱上），防受让方方向。
        2. 降水阻盘：半球升半一且降水 -> 机构真怕了，阻挡买入，真实防范让球方打出。
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
        
        # 场景1: 维持半球盘，但让球方水位异常飙升 (诱导大热)
        if start_h == live_h and water_diff >= 0.08:
            return (f"初盘和即时盘均维持【{start_h}】生死盘，但让球方水位异常飙升(+{water_diff:.3f})！"
                    "大众资金蜂拥让球方，机构顺势提升赔付门槛（诱上）。此时受让方方向的冷门风险上升，**严禁单选让球方打出！**")
                    
        # 场景2: 升盘且降水 (真实阻盘)
        is_upgrade = ('半球/一球' in live_h and '受' not in live_h) if is_home_yield else ('受半球/一球' in live_h)
        if is_upgrade and water_diff <= -0.05:
            return (f"从【{start_h}】升盘至【{live_h}】，且让球方水位大幅下降({water_diff:.3f})！"
                    "机构在通过升盘降水真实阻挡买入让球方的资金。抛弃诱盘阴谋论，**这更像真实阻上，应在最终裁决中提高让球方打出权重。**")
                    
        return ""

    @staticmethod
    def _resolve_euro_strength_side(odds, europe_odds=None):
        """用欧赔低赔方定义实力方，优先用主流欧洲公司初赔，其次临赔，最后回退到竞彩不让球赔率。"""
        vote_details = []

        def side_from_pair(home_val, away_val, tolerance=0.08):
            if home_val is None or away_val is None:
                return None
            if home_val < away_val - tolerance:
                return "home"
            if away_val < home_val - tolerance:
                return "away"
            return None

        for item in (europe_odds or []):
            company = str(item.get("company", "") or "")
            company_label = "欧赔公司"
            if "澳门" in company:
                company_label = "澳门欧赔"
            elif "bet365" in company.lower():
                company_label = "Bet365欧赔"
            elif "威" in company:
                company_label = "威廉欧赔"
            elif "立" in company:
                company_label = "立博欧赔"

            try:
                init_home = float(item.get("init_home")) if item.get("init_home") not in (None, "", "0") else None
                init_away = float(item.get("init_away")) if item.get("init_away") not in (None, "", "0") else None
                live_home = float(item.get("live_home")) if item.get("live_home") not in (None, "", "0") else None
                live_away = float(item.get("live_away")) if item.get("live_away") not in (None, "", "0") else None
            except (ValueError, TypeError):
                continue

            init_side = side_from_pair(init_home, init_away)
            live_side = side_from_pair(live_home, live_away)
            if init_side:
                vote_details.append((company_label, "初赔", init_side))
            if live_side:
                vote_details.append((company_label, "临赔", live_side))

        if not vote_details:
            nspf = (odds or {}).get("nspf", [])
            if len(nspf) == 3:
                try:
                    home_odds, away_odds = float(nspf[0]), float(nspf[2])
                    nspf_side = side_from_pair(home_odds, away_odds, tolerance=0.12)
                    if nspf_side:
                        return {
                            "side": nspf_side,
                            "label": "主队" if nspf_side == "home" else "客队",
                            "basis": f"竞彩不让球赔率低赔方（主胜{home_odds} / 客胜{away_odds}）",
                        }
                except (ValueError, TypeError):
                    pass
            return {"side": None, "label": "未分出", "basis": "欧赔未形成明确低赔方"}

        home_votes = sum(1 for _, _, side in vote_details if side == "home")
        away_votes = sum(1 for _, _, side in vote_details if side == "away")
        if home_votes == away_votes:
            preferred = next((d for d in vote_details if d[0] == "澳门欧赔" and d[1] == "初赔"), vote_details[0])
            final_side = preferred[2]
        else:
            final_side = "home" if home_votes > away_votes else "away"

        basis_lines = [f"{company}{stage}→{'主队' if side == 'home' else '客队'}" for company, stage, side in vote_details[:4]]
        return {
            "side": final_side,
            "label": "主队" if final_side == "home" else "客队",
            "basis": "；".join(basis_lines),
        }

    @staticmethod
    def _resolve_asian_giving_side(asian):
        """用亚赔定义实际让球方：优先即时盘，其次初盘；平手则视为当前无明确让球方。"""
        macau = (asian or {}).get("macau", {})
        live_line = str(macau.get("live", "") or "")
        start_line = str(macau.get("start", "") or "")

        def parse_side(line):
            if not line or "|" not in line:
                return None, ""
            handicap = line.split("|")[1].strip().replace(" ", "")
            if handicap == "平手":
                return None, handicap
            if handicap.startswith("受"):
                return "away", handicap
            return "home", handicap

        live_side, live_handicap = parse_side(live_line)
        start_side, start_handicap = parse_side(start_line)
        basis = []
        if live_handicap:
            basis.append(f"即时盘={live_handicap}")
        if start_handicap:
            basis.append(f"初盘={start_handicap}")

        if live_side is not None:
            return {
                "side": live_side,
                "label": "主队" if live_side == "home" else "客队",
                "basis": "；".join(basis),
                "handicap": live_handicap,
            }
        if start_side is not None:
            return {
                "side": start_side,
                "label": "主队" if start_side == "home" else "客队",
                "basis": "；".join(basis) + "；即时盘已退至平手",
                "handicap": start_handicap,
            }
        return {"side": None, "label": "无明确让球方", "basis": "亚赔即时/初盘均为平手或缺失", "handicap": live_handicap or start_handicap}

    @classmethod
    def _build_market_anchor_summary(cls, match_data):
        odds = match_data.get("odds", {}) or {}
        asian = match_data.get("asian_odds", {}) or {}
        europe_odds = match_data.get("europe_odds", []) or []
        asian_anchor = cls._resolve_asian_giving_side(asian)
        euro_anchor = cls._resolve_euro_strength_side(odds, europe_odds)
        return {
            "asian": asian_anchor,
            "euro": euro_anchor,
            "text": (
                f"亚赔实际让球方/上盘 = {asian_anchor['label']}（{asian_anchor['basis']}）；"
                f"欧赔实力方 = {euro_anchor['label']}（{euro_anchor['basis']}）。"
                "若竞彩让球方向与上述口径冲突，只视为官方玩法方向冲突，不覆盖“亚赔定让球方、欧赔定实力方”的判断。"
            ),
        }

    @staticmethod
    def _append_prediction_bias(text, bias):
        text = str(text or "").strip()
        bias = str(bias or "").strip()
        if not text or not bias or "预测偏向：" in text:
            return text
        return f"{text}【预测偏向：{bias}】"

    @classmethod
    def _infer_prediction_bias_from_signal_text(cls, text, asian=None):
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return ""

        explicit_pairs = [
            (r"胜[\/、]平|胜平", "胜平"),
            (r"平[\/、]负|平负", "平负"),
            (r"胜[\/、]负|胜负", "胜负"),
        ]
        for pattern, bias in explicit_pairs:
            if re.search(pattern, normalized):
                return bias

        keyword_map = [
            (["主队不胜", "防主胜", "放弃主胜", "避开主胜"], "平负"),
            (["客队不胜", "防客胜", "放弃客胜", "避开客胜"], "胜平"),
            (["主队不败"], "胜平"),
            (["客队不败"], "平负"),
            (["主胜方向", "优先考虑主胜", "锁定主胜", "主胜必须进入核心推荐", "主胜打出可能"], "胜"),
            (["客胜方向", "优先考虑客胜", "锁定客胜"], "负"),
            (["平局方向", "重点防平", "防范平局"], "平"),
        ]
        for keywords, bias in keyword_map:
            if any(keyword in normalized for keyword in keywords):
                return bias

        giving_side = cls._resolve_asian_giving_side(asian or {}).get("side")
        if giving_side == "home":
            if any(keyword in normalized for keyword in ["让球方可能确实强势", "走强队方向", "不应单凭升水直接推翻让球方优势", "真实看好主队"]):
                return "胜"
            if any(keyword in normalized for keyword in ["受让方严加防范", "诱导买入让球方", "防范反向赛果", "主队赢盘能力骤降", "谨防让球方赢球输盘或冷平"]):
                return "平负"
        elif giving_side == "away":
            if any(keyword in normalized for keyword in ["让球方可能确实强势", "走强队方向", "不应单凭升水直接推翻让球方优势", "真实看好客队"]):
                return "负"
            if any(keyword in normalized for keyword in ["受让方严加防范", "诱导买入让球方", "防范反向赛果", "客队赢盘能力骤降", "谨防让球方赢球输盘或冷平"]):
                return "胜平"

        return ""

    @classmethod
    def _format_signal_with_prediction_bias(cls, text, asian=None):
        bias = cls._infer_prediction_bias_from_signal_text(text, asian=asian)
        return cls._append_prediction_bias(text, bias)

    @classmethod
    def _detect_odds_conflict(cls, odds, asian, europe_odds=None):
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
        
        # 竞彩方向: rq < 0 = 主队让球(官方玩法视主队为让球方), rq > 0 = 客队让球
        cai_home_strong = (rq < 0)
        market_anchor = cls._build_market_anchor_summary({
            "odds": odds,
            "asian_odds": asian,
            "europe_odds": europe_odds or [],
        })
        asian_side = market_anchor["asian"]["side"]
        euro_side = market_anchor["euro"]["side"]
        
        conflicts = []
        
        # 竞彩 vs 亚指方向冲突
        if asian_side is not None and cai_home_strong != (asian_side == "home"):
            conflicts.append(
                f"竞彩让球({rq})把{'主队' if cai_home_strong else '客队'}摆成让球方，"
                f"但亚赔实际让球方以上亚指为准，应视为{market_anchor['asian']['label']}（{market_anchor['asian']['basis']}）。"
            )
        
        # 欧赔实力方 vs 竞彩让球方向冲突
        if euro_side is not None and euro_side != ("home" if cai_home_strong else "away"):
            conflicts.append(
                f"欧赔低赔方定义的实力方应为{market_anchor['euro']['label']}（{market_anchor['euro']['basis']}），"
                f"与竞彩让球({rq})给出的官方玩法方向不一致。"
            )

        if conflicts:
            conflicts.append(
                f"执行口径：让球方/上盘只按亚赔认定；实力强弱优先按欧赔低赔方认定；竞彩让球仅用于让球玩法结算，不得反向覆盖前两者。"
            )
        return ' | '.join(conflicts) if conflicts else ""

    @staticmethod
    def _count_nspf_options(rec):
        rec = (rec or "").replace("让胜", "").replace("让平", "").replace("让负", "")
        return len({k for k in ["胜", "平", "负"] if k in rec})

    @staticmethod
    def _count_rq_options(rec):
        rec = rec or ""
        return len({k for k in ["让胜", "让平", "让负"] if k in rec})

    @staticmethod
    def _parse_conf_int(conf_str):
        m = re.search(r"(\d+)", conf_str or "")
        return int(m.group(1)) if m else None

    @staticmethod
    def _clamp_confidence_line(prediction_text, max_conf):
        lines = []
        changed = False
        for line in prediction_text.splitlines():
            if "竞彩置信度" in line:
                m = re.search(r"(\d+)", line)
                if m and int(m.group(1)) > max_conf:
                    line = line.replace(m.group(1), str(max_conf), 1)
                    changed = True
            lines.append(line)
        return "\n".join(lines), changed

    @staticmethod
    def _replace_prediction_line(prediction_text, keyword, new_value):
        lines = []
        changed = False
        pattern = re.compile(rf"^(?P<prefix>.*{re.escape(keyword)}.*?[：:])\s*(?P<value>.*)$")
        for line in prediction_text.splitlines():
            match = pattern.match(line)
            if match:
                line = f"{match.group('prefix')}{new_value}"
                changed = True
            lines.append(line)
        return "\n".join(lines), changed

    @staticmethod
    def _format_dual_recommendation(tokens):
        unique_tokens = []
        for token in tokens:
            if token and token not in unique_tokens:
                unique_tokens.append(token)
        if len(unique_tokens) < 2:
            return ""
        return f"{unique_tokens[0]}(55%)/{unique_tokens[1]}(45%)"

    @staticmethod
    def _pick_nspf_dual_tokens(rec, analysis_panpei, giving_side):
        existing = [token for token in ["胜", "平", "负"] if token in (rec or "")]
        if len(existing) >= 2:
            return existing[:2]

        giving_token = "胜" if giving_side == "home" else "负" if giving_side == "away" else None
        is_induce_upper = "诱上" in analysis_panpei and "阻上" not in analysis_panpei
        is_block_upper = "阻上" in analysis_panpei and "诱上" not in analysis_panpei

        if is_induce_upper:
            target = ["平", "负"] if giving_side == "home" else ["胜", "平"] if giving_side == "away" else ["平", "负"]
        elif is_block_upper:
            target = [giving_token, "平"] if giving_token else ["胜", "平"]
        else:
            target = ["平", giving_token] if giving_token else ["胜", "平"]

        merged = []
        for token in existing + target + ["胜", "平", "负"]:
            if token and token not in merged:
                merged.append(token)
            if len(merged) >= 2:
                break
        return merged

    @staticmethod
    def _pick_rq_dual_tokens(rec, analysis_panpei):
        existing = [token for token in ["让胜", "让平", "让负"] if token in (rec or "")]
        if len(existing) >= 2:
            return existing[:2]

        if "诱上" in analysis_panpei and "阻上" not in analysis_panpei:
            target = ["让平", "让负"]
        elif "阻上" in analysis_panpei and "诱上" not in analysis_panpei:
            target = ["让平", "让胜"]
        else:
            target = ["让平", "让胜"]

        merged = []
        for token in existing + target + ["让胜", "让平", "让负"]:
            if token and token not in merged:
                merged.append(token)
            if len(merged) >= 2:
                break
        return merged

    @classmethod
    def _enforce_minimum_risk_coverage(cls, prediction_text, details, risk_policy, match_asian_odds):
        changed = False
        analysis_panpei = details.get("analysis_panpei", "") or prediction_text or ""
        nspf_rec = details.get("recommendation_nspf", "") or ""
        rq_rec = details.get("recommendation_rq", "") or ""
        giving_side = cls._resolve_asian_giving_side(match_asian_odds).get("side")
        conf_val = cls._parse_conf_int(details.get("confidence", ""))
        low_confidence = conf_val is not None and conf_val < 60

        if (risk_policy.get("must_double_nspf") or low_confidence) and cls._count_nspf_options(nspf_rec) < 2:
            dual_tokens = cls._pick_nspf_dual_tokens(nspf_rec, analysis_panpei, giving_side)
            dual_text = cls._format_dual_recommendation(dual_tokens)
            if dual_text:
                prediction_text, line_changed = cls._replace_prediction_line(prediction_text, "竞彩推荐", dual_text)
                changed = changed or line_changed

        if (risk_policy.get("must_double_rq") or low_confidence) and cls._count_rq_options(rq_rec) < 2:
            dual_tokens = cls._pick_rq_dual_tokens(rq_rec, analysis_panpei)
            dual_text = cls._format_dual_recommendation(dual_tokens)
            if dual_text:
                prediction_text, line_changed = cls._replace_prediction_line(prediction_text, "竞彩让球推荐", dual_text)
                changed = changed or line_changed

        return prediction_text, changed

    @staticmethod
    def _build_risk_policy(*, triggered_rule_ids, odds_conflict_text="", has_anchor_divergence=False):
        policy = {
            "must_cover_micro_signals": bool(triggered_rule_ids),
            "must_double_nspf": False,
            "must_double_rq": False,
            "must_explain_market_anchor": False,
            "confidence_cap": None,
        }

        if triggered_rule_ids:
            policy["must_double_nspf"] = True
            policy["must_double_rq"] = True
            policy["confidence_cap"] = 65

        if odds_conflict_text or has_anchor_divergence:
            policy["must_double_nspf"] = True
            policy["must_double_rq"] = True
            policy["must_explain_market_anchor"] = True
            policy["confidence_cap"] = min(policy["confidence_cap"], 60) if policy["confidence_cap"] is not None else 60

        return policy

    def _get_arbitration_rules_path(self):
        return os.path.join(self._get_project_base_dir(), "data", "rules", "arbitration_rules.json")

    def _load_arbitration_rules(self):
        rules_path = self._get_arbitration_rules_path()
        if not os.path.exists(rules_path):
            return []

        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
        except Exception as e:
            logger.warning(f"读取仲裁保护规则失败: {e}")
            return []

        enabled_rules = []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            normalized_rule = dict(rule)
            action_type, action_payload = normalize_arbitration_rule_action(
                normalized_rule.get("action_type"),
                normalized_rule.get("action_payload"),
                explanation=normalized_rule.get("explanation_template", ""),
            )
            normalized_rule["action_type"] = action_type
            normalized_rule["action_payload"] = action_payload
            enabled_rules.append(normalized_rule)
        return sorted(enabled_rules, key=lambda item: item.get("priority", 0), reverse=True)

    @classmethod
    def _build_arbitration_rule_context(
        cls,
        *,
        details=None,
        conflict_assessment=None,
        triggered_rule_ids=None,
        dominant_score_gap=0,
        asian_context=None,
    ):
        details = details or {}
        conflict_assessment = conflict_assessment or {}
        triggered_rule_ids = triggered_rule_ids or []
        asian_context = asian_context or {}

        missing_markers = {"", "未提取", "信息不足", "暂无", "无"}
        dimension_values = [
            details.get("arb_fundamental", "") or "",
            details.get("arb_market", "") or "",
            details.get("arb_intel", "") or "",
            details.get("arb_micro", "") or "",
        ]
        informative_dimension_count = sum(
            1 for value in dimension_values if (value or "").strip() not in missing_markers
        )
        all_dimensions_empty = all((value or "").strip() in missing_markers for value in dimension_values)

        market_value = details.get("arb_market", "") or ""
        micro_value = details.get("arb_micro", "") or ""
        final_value = details.get("arb_final", "") or details.get("recommendation_nspf", "") or ""
        fundamental_value = details.get("arb_fundamental", "") or ""
        intel_value = details.get("arb_intel", "") or ""

        market_micro_relation = cls._compare_tilt_relation(market_value, micro_value)
        final_market_relation = cls._compare_tilt_relation(final_value, market_value)
        final_fundamental_relation = cls._compare_tilt_relation(final_value, fundamental_value)
        final_intel_relation = cls._compare_tilt_relation(final_value, intel_value)

        reverse_only_from_fundamental_or_intel = (
            market_micro_relation in {"完全一致", "部分一致"}
            and final_market_relation == "明显冲突"
            and (
                final_fundamental_relation in {"完全一致", "部分一致"}
                or final_intel_relation in {"完全一致", "部分一致"}
            )
        )

        return {
            "all_dimensions_empty": all_dimensions_empty,
            "informative_dimension_count": informative_dimension_count,
            "conflict_severity": conflict_assessment.get("severity", "low"),
            "dominant_score_gap": dominant_score_gap,
            "market_micro_aligned": market_micro_relation in {"完全一致", "部分一致"},
            "reverse_only_from_fundamental_or_intel": reverse_only_from_fundamental_or_intel,
            "triggered_rule_count": len(triggered_rule_ids),
            "triggered_rule_ids": triggered_rule_ids,
            "arb_market": market_value,
            "arb_micro": micro_value,
            "arb_final": final_value,
            "arb_fundamental": fundamental_value,
            "arb_intel": intel_value,
            "asian": asian_context,
        }

    @staticmethod
    def _build_micro_rule_asian_context(asian):
        if not asian:
            return {}

        handicap_map = {
            '平手': 0, '平手/半球': 0.25, '半球': 0.5, '半球/一球': 0.75,
            '一球': 1.0, '一球/球半': 1.25, '球半': 1.5, '球半/两球': 1.75,
            '两球': 2.0, '两球/两球半': 2.25, '两球半': 2.5,
            '受平手/半球': -0.25, '受半球': -0.5, '受半球/一球': -0.75, '受一球': -1.0,
            '受一球/球半': -1.25, '受球半': -1.5
        }

        def parse(line):
            parts = (line or "").split('|')
            if len(parts) < 3:
                return None
            try:
                w1 = float(parts[0].strip().replace('↑', '').replace('↓', ''))
                h = parts[1].strip().replace(' ', '')
                w2 = float(parts[2].strip().replace('↑', '').replace('↓', ''))
                hv = handicap_map.get(h)
                if hv is None:
                    return None
                return {"w1": w1, "h": h, "hv": hv, "w2": w2}
            except Exception:
                return None

        macau = (asian or {}).get("macau", {})
        start = parse(macau.get("start", ""))
        live = parse(macau.get("live", ""))
        if not start or not live:
            return {}

        start_hv = start["hv"]
        live_hv = live["hv"]
        return {
            "start_hv": start_hv,
            "live_hv": live_hv,
            "giving_start_w": start["w1"] if start_hv >= 0 else start["w2"],
            "receiving_start_w": start["w2"] if start_hv >= 0 else start["w1"],
            "giving_live_w": live["w1"] if live_hv >= 0 else live["w2"],
            "receiving_live_w": live["w2"] if live_hv >= 0 else live["w1"],
        }

    def _evaluate_arbitration_rules(self, ctx):
        result = {
            "abort_prediction": False,
            "must_double_nspf": False,
            "must_double_rq": False,
            "confidence_cap": None,
            "override_blocked": False,
            "guard_messages": [],
            "message": "",
        }

        safe_functions = {
            "abs": abs,
            "min": min,
            "max": max,
            "len": len,
            "any": any,
            "all": all,
        }

        for rule in self._load_arbitration_rules():
            condition = rule.get("condition") or "False"
            try:
                matched = bool(
                    simpleeval.simple_eval(
                        condition,
                        names={
                            "ctx": ctx,
                            # Backward compatibility for older draft-derived rules that referenced asian directly.
                            "asian": ctx.get("asian", {}),
                        },
                        functions=safe_functions,
                    )
                )
            except Exception as e:
                logger.warning(f"执行仲裁保护规则 {rule.get('id')} 失败: {e}")
                continue

            if not matched:
                continue

            rule_name = rule.get("name") or rule.get("id") or "未命名规则"
            explanation = rule.get("explanation_template") or f"命中仲裁保护规则：{rule_name}"
            result["guard_messages"].append(explanation)
            action_type = rule.get("action_type")
            payload = rule.get("action_payload") or {}

            if action_type == "abort_prediction":
                result["abort_prediction"] = True
                result["message"] = payload.get("message") or explanation
                confidence = payload.get("confidence")
                if isinstance(confidence, (int, float)):
                    result["confidence_cap"] = int(confidence)
            elif action_type == "force_double":
                result["must_double_nspf"] = payload.get("nspf", True)
                result["must_double_rq"] = payload.get("rq", True)
                confidence_cap = payload.get("confidence_cap")
                if isinstance(confidence_cap, (int, float)):
                    current_cap = result["confidence_cap"]
                    result["confidence_cap"] = int(confidence_cap) if current_cap is None else min(current_cap, int(confidence_cap))
            elif action_type == "cap_confidence":
                confidence_cap = payload.get("confidence_cap")
                if isinstance(confidence_cap, (int, float)):
                    current_cap = result["confidence_cap"]
                    result["confidence_cap"] = int(confidence_cap) if current_cap is None else min(current_cap, int(confidence_cap))
            elif action_type == "forbid_override":
                result["override_blocked"] = True
                if not any(keyword in explanation for keyword in ["推翻", "弱证据"]):
                    result["guard_messages"].append(f"弱证据不得推翻强盘口：{rule_name}")
            elif action_type == "require_override_reason":
                result["guard_messages"].append(f"若要推翻市场方向，必须补充明确推翻原因：{rule_name}")

        return result

    @classmethod
    def _apply_arbitration_actions(cls, result_text, details, actions):
        if not actions:
            return result_text, False

        changed = False
        updated_text = result_text

        if actions.get("abort_prediction"):
            skip_text = "暂无有效预测（建议回避）"
            for keyword in ["竞彩推荐", "竞彩让球推荐", "最终仲裁方向"]:
                updated_text, line_changed = cls._replace_prediction_line(updated_text, keyword, skip_text)
                changed = changed or line_changed

            message = actions.get("message") or "信息不足以形成预测，建议回避"
            if message not in updated_text:
                updated_text += f"\n\n> 仲裁保护规则：{message}"
                changed = True

        confidence_cap = actions.get("confidence_cap")
        if confidence_cap is not None:
            updated_text, line_changed = cls._clamp_confidence_line(updated_text, int(confidence_cap))
            changed = changed or line_changed

        return updated_text, changed

    @staticmethod
    def _extract_json_block_from_review_text(review_text, heading):
        text = review_text or ""
        pattern = re.compile(
            rf"\n*##\s*{re.escape(heading)}\s*```json\s*(?P<json>\[[\s\S]*?\])\s*```",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return text.strip(), []

        json_text = match.group("json").strip()
        try:
            payload = json.loads(json_text)
            if not isinstance(payload, list):
                payload = []
        except Exception as e:
            logger.warning(f"解析复盘区块 {heading} 失败: {e}")
            payload = []

        cleaned = (text[: match.start()] + text[match.end() :]).strip()
        return cleaned, payload

    @classmethod
    def _extract_review_structured_payloads(cls, review_text):
        cleaned_text, case_mappings = cls._extract_json_block_from_review_text(review_text, "结构化盘口复盘映射")
        cleaned_text, rule_drafts = cls._extract_json_block_from_review_text(cleaned_text, "结构化规则草稿")
        return cleaned_text, case_mappings, rule_drafts

    @staticmethod
    def _append_review_validation_section(review_text, warnings):
        if not warnings:
            return review_text
        section_lines = [
            "",
            "## 复盘完整性校验",
            "",
            "以下问题由程序化校验发现，说明本次复盘仍存在待补充项：",
            "",
        ]
        section_lines.extend([f"- {warning}" for warning in warnings])
        return (review_text.rstrip() + "\n" + "\n".join(section_lines)).strip()

    @staticmethod
    def _render_market_review_entries(case_mappings):
        if not case_mappings:
            return ""

        lines = [
            "## 规则修正入口",
            "",
            "以下入口由结构化盘口复盘映射自动生成，用于把盘口错因拆解与规则修正动作绑定起来：",
            "",
        ]
        for case in case_mappings:
            match_num = case.get("match_num", "未知场次")
            matchup = case.get("matchup", "未知对阵")
            disposition = case.get("disposition", "未分类")
            based_on_rule_id = case.get("based_on_rule_id", "")
            target_scope = case.get("recommended_target_scope", "")
            summary = case.get("entry_summary") or case.get("market_chain_summary") or "未提供"
            lines.append(f"### {match_num} | {matchup}")
            lines.append(f"- 处置类型：`{disposition}`")
            if based_on_rule_id:
                lines.append(f"- 关联旧规则：`{based_on_rule_id}`")
            if target_scope:
                lines.append(f"- 建议入口：`{target_scope}`")
            lines.append(f"- 快速摘要：{summary}")
            lines.append("")
        return "\n".join(lines).strip()

    def _build_retry_messages(
        self,
        *,
        result_text,
        details,
        risk_policy,
        match_asian_odds,
        triggered_rule_ids,
        match_data=None,
        conflict_assessment=None,
    ):
        analysis_panpei = details.get("analysis_panpei", "") or ""
        analysis_arbitration = details.get("analysis_arbitration", "") or ""
        nspf_rec = details.get("recommendation_nspf", "") or ""
        rq_rec = details.get("recommendation_rq", "") or ""
        conf_val = self._parse_conf_int(details.get("confidence", ""))

        giving_anchor = self._resolve_asian_giving_side(match_asian_odds)
        giving_side = giving_anchor.get("side")
        giving_label = giving_anchor.get("label", "让球方")
        giving_nspf_token = "胜" if giving_side == "home" else "负" if giving_side == "away" else ""
        giving_desc = f"{giving_label}（让球方）"
        retry_msgs = []

        required_arbitration_items = {
            "基本面方向": details.get("arb_fundamental", "") or "",
            "盘赔方向": details.get("arb_market", "") or "",
            "情报佐证结论": details.get("arb_intel", "") or "",
            "微观规则结论": details.get("arb_micro", "") or "",
            "最终仲裁方向": details.get("arb_final", "") or "",
            "推翻原因": details.get("arb_override_reason", "") or "",
        }
        if not analysis_arbitration:
            retry_msgs.append(
                "你遗漏了【四维仲裁】。必须逐行写出：基本面方向、盘赔方向、情报佐证结论、微观规则结论、最终仲裁方向、推翻原因，然后才能给出最终预测。"
            )
        else:
            missing_arbitration = [label for label, value in required_arbitration_items.items() if not value]
            if missing_arbitration:
                retry_msgs.append(
                    "你在【四维仲裁】中遗漏了以下必填项："
                    + "、".join(missing_arbitration)
                    + "。请按固定六行完整补齐。"
                )
            elif conflict_assessment and conflict_assessment.get("severity") == "high":
                arb_override_reason = details.get("arb_override_reason", "") or ""
                arb_final = details.get("arb_final", "") or ""
                conflict_points = conflict_assessment.get("conflict_points") or []
                conflict_context = ""
                if conflict_points:
                    conflict_context = " 当前程序识别到的冲突点包括：" + "；".join(conflict_points[:4]) + "。"
                if "无明显冲突" in arb_override_reason:
                    retry_msgs.append(
                        "程序化冲突矩阵已判定当前至少存在两处高冲突证据，但你在【四维仲裁】中仍写“无明显冲突，无需推翻”。请明确说明：是基本面、盘口、情报还是微观规则中的哪一层推翻了哪一层。"
                        + conflict_context
                    )
                if arb_final and self._compare_tilt_relation(arb_final, details.get("arb_market", "") or "") == "明显冲突" and "推翻" not in arb_override_reason:
                    retry_msgs.append(
                        "当前最终仲裁方向与盘赔方向在结构化层面明显冲突，但“推翻原因”没有解释谁推翻了谁。请重写【四维仲裁】并补全推翻链路。"
                        + conflict_context
                    )

        if giving_side is not None:
            is_induce_upper = "诱上" in analysis_panpei
            is_block_upper = "阻上" in analysis_panpei
            arb_override_reason = details.get("arb_override_reason", "") or ""

            if is_induce_upper and giving_nspf_token and giving_nspf_token in nspf_rec and not is_block_upper:
                retry_msgs.append(
                    f"你在【盘赔深度解析】中判断机构意图为“诱上”（诱导买入{giving_desc}），但最终不让球推荐却仍包含了让球方方向，说明‘盘口判断’与‘最终结论’存在冲突。请回看基本面摘要、情报要点、欧亚锚点后重新判断：到底是诱上结论需要修正，还是最终推荐需要调整；禁止只改推荐而不重写依据。"
                )
                if analysis_arbitration and "推翻" not in arb_override_reason and "无明显冲突" in arb_override_reason:
                    retry_msgs.append(
                        "当前【盘赔深度解析】与最终推荐明显存在冲突，但你在【四维仲裁】的“推翻原因”里仍写成“无明显冲突”。请明确说明：到底是哪一个维度推翻了盘口方向，还是盘口方向本身需要改判。"
                    )
            elif is_block_upper and giving_nspf_token and giving_nspf_token not in nspf_rec and not is_induce_upper:
                retry_msgs.append(
                    f"你在【盘赔深度解析】中判断机构意图为“阻上”（真实防范{giving_desc}），但最终不让球推荐却没有覆盖让球方直接赢球方向，说明‘盘口判断’与‘最终结论’存在冲突。请结合基本面摘要、情报要点和欧赔实力方重新核验：到底是阻上判断需要修正，还是最终推荐需要补充；禁止只改结论不解释原因。"
                )
                if analysis_arbitration and "推翻" not in arb_override_reason and "无明显冲突" in arb_override_reason:
                    retry_msgs.append(
                        "当前【盘赔深度解析】与最终推荐明显存在冲突，但你在【四维仲裁】的“推翻原因”里没有解释谁推翻了谁。请重写仲裁段。"
                    )

        shallow_showweak_warning = self._detect_shallow_showweak_induce_down(match_asian_odds)
        if shallow_showweak_warning and giving_side is not None and giving_nspf_token and giving_nspf_token not in nspf_rec:
            retry_msgs.append(
                "系统已触发【浅盘示弱诱下预警】：\n"
                f"{shallow_showweak_warning}\n"
                "你刚才的不让球推荐完全排除了让球方直接赢球方向。请重新核验：这究竟是基本面/情报已经足以证伪让球方，还是你把示弱控热误读成了真实走弱；若维持当前结论，必须在盘赔解析中给出更充分的证据链。"
            )

        if risk_policy.get("must_cover_micro_signals"):
            if not analysis_panpei:
                retry_msgs.append("你必须输出【盘赔深度解析】并逐条回应系统触发的🧩盘赔微观信号（引用 [rule_id]）。")
            else:
                if "盘赔微观信号规则匹配" not in analysis_panpei:
                    retry_msgs.append("你在【盘赔深度解析】中遗漏了“盘赔微观信号规则匹配：...”这一行。若有命中规则，必须列出对应 [rule_id]；若无命中，也要明确写“无盘赔微观信号规则匹配”。")
                missing = [rid for rid in triggered_rule_ids if rid not in analysis_panpei]
                if missing:
                    retry_msgs.append(
                        f"你在【盘赔深度解析】中遗漏了对以下触发微观信号的回应：{missing}。请逐条引用对应 [rule_id] 并说明该信号成立与否、以及它防住了哪个方向。"
                    )
        elif analysis_panpei and "盘赔微观信号规则匹配" not in analysis_panpei:
            retry_msgs.append("即使本场没有命中微观规则，你也必须在【盘赔深度解析】中显式写出“盘赔微观信号规则匹配：无盘赔微观信号规则匹配”。")

        if risk_policy.get("must_explain_market_anchor"):
            if "亚赔实际让球方" not in result_text or "欧赔实力方" not in result_text:
                retry_msgs.append(
                    "本场已触发【P0-4 赔率方向矛盾熔断】。你必须明确写出“亚赔实际让球方是谁、欧赔实力方是谁”，并说明这是欧亚分工，不是二选一覆盖。"
                )

        low_confidence = conf_val is not None and conf_val < 60

        if (risk_policy.get("must_double_nspf") or low_confidence) and self._count_nspf_options(nspf_rec) < 2:
            if risk_policy.get("must_cover_micro_signals"):
                retry_msgs.append("本场已触发🧩盘赔微观信号，风险必须对称覆盖：不让球推荐必须双选，绝对禁止单选。")
            elif low_confidence:
                retry_msgs.append("当前竞彩置信度低于 60，不让球推荐必须双选覆盖风险，绝对禁止单选。")
            else:
                retry_msgs.append("本场已触发【P0-4 赔率方向矛盾熔断】：不让球推荐必须双选覆盖风险，绝对禁止单选。")

        if (risk_policy.get("must_double_rq") or low_confidence) and self._count_rq_options(rq_rec) < 2:
            if risk_policy.get("must_cover_micro_signals"):
                retry_msgs.append("本场已触发🧩盘赔微观信号：竞彩让球推荐必须双选，绝对禁止单选。")
            elif low_confidence:
                retry_msgs.append("当前竞彩置信度低于 60，竞彩让球推荐必须双选覆盖风险，绝对禁止单选。")
            else:
                retry_msgs.append("本场已触发【P0-4 赔率方向矛盾熔断】：竞彩让球推荐必须双选覆盖风险，绝对禁止单选。")

        confidence_cap = risk_policy.get("confidence_cap")
        if confidence_cap is not None and conf_val is not None and conf_val > confidence_cap:
            if confidence_cap == 65:
                retry_msgs.append("本场已触发🧩盘赔微观信号：竞彩置信度上限为 65，请降低置信度或解释为何可以推翻微观信号。")
            else:
                retry_msgs.append(
                    f"本场已触发【P0-4 赔率方向矛盾熔断】：竞彩置信度必须压到 {confidence_cap} 或以下，严禁再输出 {confidence_cap} 以上的高置信度。"
                )

        if match_data and (match_data.get("leisu_intelligence") or {}):
            missing_markers = [marker for marker in ["让球方", "受让方", "欧赔实力方"] if marker not in analysis_panpei]
            if missing_markers:
                retry_msgs.append(
                    "本场已注入结构化情报。你在【盘赔深度解析】中必须把情报归类到“支持让球方 / 支持受让方 / 支持欧赔实力方”的框架下，当前遗漏了："
                    + "、".join(missing_markers)
                    + "。请重写相关段落。"
                )
            elif "欧赔实力方" not in analysis_panpei:
                retry_msgs.append(
                    "本场已注入结构化情报。请在【盘赔深度解析】中显式写出“欧赔实力方”，并判断哪些情报是在支持欧赔长期低赔保护的一方。"
                )
            if not any(keyword in analysis_panpei for keyword in ["借题发挥", "借情报", "控热", "造热"]):
                retry_msgs.append(
                    "本场已注入结构化情报。请在【盘赔深度解析】中明确判断：哪些情报是真实利好/利空，哪些只是机构借题发挥或借情报控热，禁止只罗列情报而不做归类。"
                )

        return retry_msgs

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
        """解析亚指初盘->即时盘变化，输出结构化摘要。这里的 left/right 仅表示盘口文本左右两侧，不直接等同于上/下盘。"""
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

        def compare_handicap_strength(start_val, live_val):
            if start_val is None or live_val is None or start_val == live_val:
                return ""
            if start_val == 0:
                return "升盘" if abs(live_val) > 0 else ""
            if live_val == 0:
                return "退盘"
            if (start_val > 0 and live_val > 0) or (start_val < 0 and live_val < 0):
                return "升盘" if abs(live_val) > abs(start_val) else "退盘"
            return "升盘" if abs(live_val) > abs(start_val) else "退盘"
        
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
                change_label = compare_handicap_strength(h_s, h_l)
                if change_label:
                    parts_summary.append(f"{change_label}({s['handicap']}→{l['handicap']})")
            
            # 左侧水位变化（澳门/Bet365 原始盘口文本左侧）
            w_diff = l['water_up'] - s['water_up']
            if abs(w_diff) >= 0.03:
                direction = '↑升水' if w_diff > 0 else '↓降水'
                parts_summary.append(f"左侧水位{direction}({s['water_up']:.2f}→{l['water_up']:.2f})")
            
            # 右侧水位变化（澳门/Bet365 原始盘口文本右侧）
            wd_diff = l['water_down'] - s['water_down']
            if abs(wd_diff) >= 0.03:
                direction = '↑升水' if wd_diff > 0 else '↓降水'
                parts_summary.append(f"右侧水位{direction}({s['water_down']:.2f}→{l['water_down']:.2f})")
            
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

        def is_upgrade(start_val, live_val):
            if start_val is None or live_val is None or start_val == live_val:
                return False
            if start_val == 0:
                return abs(live_val) > 0
            if live_val == 0:
                return False
            if (start_val > 0 and live_val > 0) or (start_val < 0 and live_val < 0):
                return abs(live_val) > abs(start_val)
            return abs(live_val) > abs(start_val)
        
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
            
            # 检测升盘：对主让和客让统一按“让球力度是否加深”判断
            upgraded = is_upgrade(hs, hl)
            # 检测上盘水位上升（让球方/更优方水位）
            water_rise = lw1 - sw1 if hs >= 0 else lw2 - sw2
            
            if upgraded and water_rise >= 0.05:
                broker_name = '澳门' if broker == 'macau' else 'Bet365'
                level = '🔴高危' if water_rise >= 0.08 else '⚠️预警'
                warnings.append(
                    f"{broker_name}{level}: 盘口从{sh}升至{lh}，"
                    f"但让球方水位同步抬升{(water_rise*100):.0f}个点——"
                    f"机构升盘却不降水，表明并非真实看好让球方，"
                    f"此盘水背离是诱上信号，最终裁决中应重点覆盖受让方方向风险。"
                )
            elif upgraded and water_rise >= 0.03:
                broker_name = '澳门' if broker == 'macau' else 'Bet365'
                warnings.append(
                    f"{broker_name}: 盘口从{sh}升至{lh}，"
                    f"让球方水位微升{(water_rise*100):.0f}个点——"
                    f"升盘未伴随明显降水，信心不扎实，需谨慎对待让球方取胜。"
                )
        
        return ' | '.join(warnings) if warnings else ""

    @staticmethod
    def _detect_euro_asian_divergence(odds, asian, europe_odds=None):
        """
        计算欧赔隐含概率，并对比实际亚指，检测“欧亚背离”冷门预警。
        逻辑：
        1. 从竞彩不让球赔率 (NSPF) 提取主平负赔率。
        2. 计算返还率 (Return Rate) = 1 / (1/win + 1/draw + 1/lose)。
        3. 计算真实隐含概率 = (1/odds) * Return Rate。
        4. 根据欧赔实力方对应的隐含胜率映射“理论亚盘”。
        5. 对比实际澳门初盘，若“理论应让深，实际让浅”或“理论应受深，实际受浅”，则说明欧亚表达存在明显背离。
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
            
            # 确定谁是强势方：方向优先服从欧赔低赔方口径，避免与市场锚点出现双轨解释
            euro_anchor = LLMPredictor._resolve_euro_strength_side(odds, europe_odds or [])
            if euro_anchor.get("side") == "home":
                is_home_strong = True
                strong_prob = home_prob
            elif euro_anchor.get("side") == "away":
                is_home_strong = False
                strong_prob = away_prob
            else:
                strong_prob = max(home_prob, away_prob)
                is_home_strong = home_prob >= away_prob
            
            # 4. 理论亚盘映射表 (欧赔实力方胜率区间 -> 理论盘口深度)
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
                
            # 若欧赔实力方为客队，则理论亚盘应体现为“主队受让 / 客队让球”
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
                
            def format_theory_line(strong_side, handicap_str):
                if handicap_str == "平手":
                    return "理论应开【平手】"
                if strong_side == "home":
                    return f"理论应开主队让【{handicap_str}】"
                return f"理论应开主队受让【{handicap_str}】"

            # 6. 对比与预警：只表达“欧赔实力方 vs 亚指让步”的背离，不再把主队默认等同于强方/上盘
            divergence = theory_handicap_val - actual_handicap_val
            
            warnings = []
            team_strong = "主队" if is_home_strong else "客队"
            theory_line = format_theory_line("home" if is_home_strong else "away", theory_handicap_str)
            
            # 背离达到 0.5 (即相差两个盘口，比如理论一球，实际半球)
            if abs(divergence) >= 0.5:
                if is_home_strong and divergence > 0:
                    warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，{theory_line}；但实际亚指初盘仅开【{actual_handicap_str}】。欧亚严重背离！实际让步远浅于欧赔实力表达，机构在刻意降低买入{team_strong}方向的门槛，属于明显的诱上风险；最终裁决中应重点评估{team_strong}不胜风险。")
                elif not is_home_strong and divergence < 0:
                    warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，{theory_line}；但实际亚指初盘仅开【{actual_handicap_str}】。欧亚严重背离！机构刻意降低{team_strong}让步门槛诱导买入，属于明显的诱上风险；最终裁决中应重点评估{team_strong}不胜风险。")
                elif is_home_strong and divergence < 0:
                     warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，{theory_line}；但实际亚指初盘强开【{actual_handicap_str}】深盘。机构在利用深盘和高门槛阻挡资金买入{team_strong}方向，属于典型“阻上”风险；最终裁决中应重点评估{team_strong}打出可能。")
                elif not is_home_strong and divergence > 0:
                     warnings.append(f"欧赔隐含{team_strong}胜率为{strong_prob:.1%}，{theory_line}；但实际亚指初盘强开【{actual_handicap_str}】深盘。此为典型“阻上”风险；最终裁决中应重点评估{team_strong}打出可能。")
            
            return " | ".join(warnings)
            
        except Exception as e:
            return ""

    @staticmethod
    def _detect_shallow_water_trap(asian, odds):
        """
        检测浅盘（平手、平半）临场升水诱下陷阱（04-30复盘新增）。
        当让球方水位从低水区（≤0.85）剧烈攀升至高水区（≥1.00），且盘口未跟随调整时，
        此形态极度疑似机构在利用“升水”制造让球方获胜不稳的恐慌感。
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
            
        # 获取让球方水位（澳门数据：主队水位 | 盘口 | 客队水位）
        def get_giving_water(line, handicap):
            parts = line.split('|')
            if len(parts) < 3: return None
            try:
                left = float(parts[0].strip().replace('↑','').replace('↓',''))
                right = float(parts[2].strip().replace('↑','').replace('↓',''))
                return right if str(handicap).startswith('受') else left
            except:
                return None
                
        start_w = get_giving_water(start, start_h)
        live_w = get_giving_water(live, live_h)
        
        if start_w is None or live_w is None:
            return ""
            
        # 触发条件：初盘低水(≤0.85)，临场高水(≥1.00)
        if start_w <= 0.85 and live_w >= 1.00:
            giving_side = "客队" if start_h.startswith('受') else "主队" if start_h != "平手" else "让球方"
            nspf = odds.get('nspf', [])
            odds_str = ""
            if len(nspf) == 3:
                ref_odds = nspf[2] if giving_side == "客队" else nspf[0]
                odds_str = f"（当前{giving_side}直接赢球赔率 {ref_odds}）"
                
            return (f"盘口维持【{start_h}】浅盘，但让球方（{giving_side}）水位从初盘低水({start_w})剧烈攀升至即时高水({live_w})！"
                    f"此为典型的“低水升水诱下盘”操作，机构在利用“升水”这一表面利空形态，制造{giving_side}“让球无力”的恐慌感，从而将热度驱赶至受让方方向。"
                    f"{odds_str} 严禁仅因水位大涨得出“{giving_side}不胜”的结论，必须强制增加对让球方直接赢球的考量权重！")
            
        return ""

    @staticmethod
    def _detect_shallow_showweak_induce_down(asian):
        """
        检测浅盘（平半/半球）下的“示弱阻上/诱下”高危形态（05-01复盘新增）。
        典型特征：
        1) 半球低水退至平半并抬升让球方水位（退盘+涨水），下盘受让水位反而更“舒适”（低水/中低水）。
        2) 平半长期维持极低水但始终不升盘（控赔而非信心不足）。
        3) 半球盘让球方处于中高水震荡但盘口不退（制造阻力而非真实看衰）。
        """
        if not asian:
            return ""

        macau = asian.get("macau", {})
        start = macau.get("start", "")
        live = macau.get("live", "")
        if not start or not live or "|" not in start or "|" not in live:
            return ""

        def parse_line(line):
            parts = line.split("|")
            if len(parts) < 3:
                return None
            try:
                hw = float(parts[0].strip().replace("↑", "").replace("↓", ""))
                hh = parts[1].strip().replace(" ", "")
                aw = float(parts[2].strip().replace("↑", "").replace("↓", ""))
                return hw, hh, aw
            except Exception:
                return None

        parsed_start = parse_line(start)
        parsed_live = parse_line(live)
        if not parsed_start or not parsed_live:
            return ""

        shw, sh, saw = parsed_start
        lhw, lh, law = parsed_live

        handicap_map = {
            "平手": 0.0,
            "平手/半球": 0.25,
            "半球": 0.5,
            "半球/一球": 0.75,
            "一球": 1.0,
            "一球/球半": 1.25,
            "球半": 1.5,
            "受平手/半球": -0.25,
            "受半球": -0.5,
            "受半球/一球": -0.75,
            "受一球": -1.0,
            "受一球/球半": -1.25,
            "受球半": -1.5,
        }

        shv = handicap_map.get(sh, None)
        lhv = handicap_map.get(lh, None)
        if shv is None or lhv is None:
            return ""

        favorite_is_home = shv > 0
        favorite_start_w = shw if favorite_is_home else saw
        favorite_live_w = lhw if favorite_is_home else law
        underdog_live_w = law if favorite_is_home else lhw

        warnings = []

        is_shallow = abs(shv) in (0.25, 0.5)
        if not is_shallow:
            return ""

        is_same_side = (shv == 0 and lhv == 0) or (shv * lhv > 0)
        is_retreat = is_same_side and abs(lhv) < abs(shv)

        if abs(shv) == 0.5 and is_retreat and abs(lhv) <= 0.25:
            if favorite_start_w <= 0.82 and (favorite_live_w - favorite_start_w) >= 0.06 and underdog_live_w <= 0.88:
                warnings.append(
                    f"初盘【{sh}】让球方低水({favorite_start_w})，即时退至【{lh}】且让球方水位大幅抬升至({favorite_live_w})，"
                    f"下盘受让水位({underdog_live_w})偏低更“舒适”。这很像机构“示弱阻上、诱导下盘”的操盘：退盘+涨水未必看衰让球方，反而在驱赶热度去下盘。"
                )

        if abs(shv) == 0.25 and sh == lh:
            if favorite_start_w <= 0.80 and favorite_live_w <= 0.82:
                warnings.append(
                    f"盘口长期维持【{sh}】且让球方极低水({favorite_live_w})但始终不升盘。此形态更像“浅让控赔”而非信心不足，"
                    f"严禁把“不升盘”线性等同于“上盘不稳”，需提高让球方不败/赢球权重。"
                )

        if abs(shv) == 0.5 and sh == lh:
            if favorite_start_w >= 0.93 and 0.86 <= favorite_live_w <= 0.92:
                warnings.append(
                    f"【{sh}】让球方处于中高水区({favorite_start_w}→{favorite_live_w})但盘口不退。此类“高水不退”常用于制造阻力恐吓，"
                    f"不等于机构真实看衰让球方，避免默认推下盘。"
                )

        return " | ".join(warnings)

    @staticmethod
    def _get_league_hint(league):
        """返回联赛特异性提示，帮助LLM快速校准预期"""
        if not league:
            return ""
        lg = league.strip()
        # 英冠单独处理，避免被“次级联赛”分支提前吞掉
        if '英冠' in lg:
            return "英冠对抗强、赛程密，盘口噪音较大。浅盘更要结合受让方舒适度与临场水位，避免把主场题材直接当成硬支撑。"
        # 杯赛（战意与轮换扰动大）
        if any(d in lg for d in ['英足总杯', '足总杯', '杯']):
            return "杯赛战意与轮换扰动更大，基本面优势必须结合盘口态度验证，不能把名气优势直接等同于稳胆。"
        # 沙特联赛（盘口变动敏感性高）
        if '沙特' in lg:
            return "沙特联赛盘口变动陷阱多，升盘+升水更常对应诱上风险。应优先解释资金驱动与盘口舒适度，不要把升盘直接当作阻上。"
        # 防守型联赛 (小球倾向)
        if any(d in lg for d in ['法甲', '葡超', '西甲']):
            return "该联赛为防守型联赛，深盘优先防小球和赢球输盘，忌盲目推3+球"
        # 大球联赛 (攻击倾向)
        if any(d in lg for d in ['美职', '澳超', '荷甲', '荷乙']):
            return "该联赛为大开大合型，若进攻数据明显碾压，可提高大比分与让球方打出权重。"
        # 次级联赛 (盘口操控更严重)
        if any(d in lg for d in ['英甲', '德乙', '法乙', '日乙', 'K2']):
            return "次级联赛盘口操纵更严重，退盘升水信号务必高度重视"
        # 北欧冷门联赛
        if any(d in lg for d in ['挪超', '瑞超', '芬超']):
            return "北欧联赛季节性波动与主客远征差异明显，深盘场景要优先核对盘力是否匹配，不要把主场优势直接等同于可轻松打穿。"
        # 日韩联赛
        if any(d in lg for d in ['日职', '韩K']):
            return "日韩联赛节奏快、战意受盘外因素影响大，注意临场变数"
        # 五大联赛及葡超（主流联赛，水位示弱常为诱下）
        if any(d in lg for d in ['英超', '意甲', '德甲']):
            return "主流联赛中浅盘示弱更常见反向吸筹；若让球方基本面并不差，不要仅因升水或示弱就直接下利空结论。"
        # 其他二线联赛（如葡超、比甲、瑞士超等，盘赔背离预警）
        return "非主流联赛关注度低、资金体量更薄，盘口背离更容易放大。若深盘出现让球方水位不降反升，应优先视为虚假繁荣信号并评估受让方方向风险。"

    @staticmethod
    def parse_prediction_details(prediction_text):
        """提取详细的预测结果，拆分为推荐、进球数、比分、信心三个部分"""
        details = {
            'recommendation': '暂无',
            'recommendation_nspf': '暂无',
            'recommendation_rq': '暂无',
            'analysis_panpei': '',
            'analysis_arbitration': '',
            'arb_fundamental': '',
            'arb_market': '',
            'arb_intel': '',
            'arb_micro': '',
            'arb_final': '',
            'arb_override_reason': '',
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

        panpei_match = re.search(
            r'【盘赔深度解析】(?:\*\*)?[：:]\s*(.*?)(?=\n\s*-\s*\*\*【四维仲裁】|\n\s*-\s*【四维仲裁】|\n\s*\*\*【四维仲裁】|\n\s*【四维仲裁】|\n\s*-\s*\*\*【核心风控提示】|\n\s*-\s*【核心风控提示】|\n\s*\*\*【核心风控提示】|\n\s*【核心风控提示】|$)',
            prediction_text,
            re.DOTALL
        )
        if panpei_match:
            details['analysis_panpei'] = panpei_match.group(1).strip()

        arbitration_match = re.search(
            r'【四维仲裁】(?:\*\*)?[：:]\s*(.*?)(?=\n\s*-\s*\*\*【核心风控提示】|\n\s*-\s*【核心风控提示】|\n\s*\*\*【核心风控提示】|\n\s*【核心风控提示】|$)',
            prediction_text,
            re.DOTALL
        )
        if arbitration_match:
            arbitration_text = arbitration_match.group(1).strip()
            details['analysis_arbitration'] = arbitration_text
            field_patterns = {
                'arb_fundamental': r'基本面方向[：:]\s*([^\n]+)',
                'arb_market': r'盘赔方向[：:]\s*([^\n]+)',
                'arb_intel': r'情报佐证结论[：:]\s*([^\n]+)',
                'arb_micro': r'微观规则结论[：:]\s*([^\n]+)',
                'arb_final': r'最终仲裁方向[：:]\s*([^\n]+)',
                'arb_override_reason': r'推翻原因[：:]\s*([^\n]+)',
            }
            for key, pattern in field_patterns.items():
                match = re.search(pattern, arbitration_text)
                if match:
                    details[key] = re.sub(r'[\*]', '', match.group(1).strip())
                
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
3. **硬核盘口逻辑推演**：将亚指/欧指变化转化为“机构意图”。例如：“本场比赛亚赔让球方处于X档让步高度，这一盘口定位与欧赔实力方表达是否匹配...从盘口逻辑来看，机构敢于开出深盘/浅盘，说明其对让球方打出持肯定/怀疑态度，意在平衡资金或利用题材制造悬念”。
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

    def generate_post_mortem(self, date, accuracy_report, return_rule_drafts=False):
        """
        V2: 基于程序化计算的准确率报告，让LLM只做洞察分析（不再自行判断对错）。
        accuracy_report: compute_accuracy_report() 的输出
        """
        logger.info(f"开始基于结构化数据生成 {date} 的深度复盘报告，窗口: {accuracy_report.get('batch_label', date)}，共 {accuracy_report['overall']['total']} 场")
        
        if not accuracy_report or accuracy_report["overall"]["total"] == 0:
            empty_text = "该日无已完成比赛或暂无准确率数据，无法生成复盘报告。"
            return (empty_text, []) if return_rule_drafts else empty_text
        
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

        def _clean_cell(value):
            text = str(value or "无")
            return text.replace("\n", " ").replace("|", "｜").strip() or "无"

        dim_order = ["基本面", "盘赔", "情报", "微观规则"]
        dim_summary = {
            name: {"hit": 0, "wrong": 0, "insufficient": 0}
            for name in dim_order + ["AgentC最终"]
        }

        for match in accuracy_report["matches"]:
            dim_reviews = match.get("dim_reviews", {}) or {}
            for dim_name in dim_order:
                status = ((dim_reviews.get(dim_name) or {}).get("status")) or "信息不足"
                if status == "命中":
                    dim_summary[dim_name]["hit"] += 1
                elif status == "错误":
                    dim_summary[dim_name]["wrong"] += 1
                else:
                    dim_summary[dim_name]["insufficient"] += 1

            final_status = ((dim_reviews.get("final") or {}).get("status")) or "信息不足"
            if final_status == "命中":
                dim_summary["AgentC最终"]["hit"] += 1
            elif final_status == "错误":
                dim_summary["AgentC最终"]["wrong"] += 1
            else:
                dim_summary["AgentC最终"]["insufficient"] += 1

        dim_summary_lines = []
        for dim_name in dim_order + ["AgentC最终"]:
            stats = dim_summary[dim_name]
            dim_summary_lines.append(
                f"| {dim_name} | {stats['hit']} | {stats['wrong']} | {stats['insufficient']} |"
            )
        dim_summary_table = "\n".join(dim_summary_lines) if dim_summary_lines else "无"

        comparison_lines = []
        for match in accuracy_report["matches"][:40]:
            dim_reviews = match.get("dim_reviews", {}) or {}
            comparison_lines.append(
                f"| {match['match_num']} | {_clean_cell(match['home'])} vs {_clean_cell(match['away'])} | "
                f"{_clean_cell(match['actual_nspf'])} | "
                f"{_clean_cell(match.get('arb_fundamental'))} ({_clean_cell((dim_reviews.get('基本面') or {}).get('status'))}) | "
                f"{_clean_cell(match.get('arb_market'))} ({_clean_cell((dim_reviews.get('盘赔') or {}).get('status'))}) | "
                f"{_clean_cell(match.get('arb_intel'))} ({_clean_cell((dim_reviews.get('情报') or {}).get('status'))}) | "
                f"{_clean_cell(match.get('arb_micro'))} ({_clean_cell((dim_reviews.get('微观规则') or {}).get('status'))}) | "
                f"{_clean_cell(match.get('arb_final'))} ({_clean_cell((dim_reviews.get('final') or {}).get('status'))}) |"
            )
        comparison_table = "\n".join(comparison_lines) if comparison_lines else "无"

        agentc_case_blocks = []
        for match in errors[:20]:
            dim_reviews = match.get("dim_reviews", {}) or {}
            agentc_case_blocks.append(
                "\n".join(
                    [
                        f"#### {match['match_num']} | {_clean_cell(match['home'])} vs {_clean_cell(match['away'])}",
                        f"- 实际赛果：{_clean_cell(match['actual_score'])} -> {_clean_cell(match['actual_nspf'])}",
                        f"- Agent C 最终仲裁：{_clean_cell(match.get('arb_final'))}（{_clean_cell((dim_reviews.get('final') or {}).get('status'))}）",
                        f"- 基本面方向：{_clean_cell(match.get('arb_fundamental'))}（{_clean_cell((dim_reviews.get('基本面') or {}).get('status'))}）",
                        f"- 盘赔方向：{_clean_cell(match.get('arb_market'))}（{_clean_cell((dim_reviews.get('盘赔') or {}).get('status'))}）",
                        f"- 情报佐证结论：{_clean_cell(match.get('arb_intel'))}（{_clean_cell((dim_reviews.get('情报') or {}).get('status'))}）",
                        f"- 微观规则结论：{_clean_cell(match.get('arb_micro'))}（{_clean_cell((dim_reviews.get('微观规则') or {}).get('status'))}）",
                        f"- 推翻原因：{_clean_cell(match.get('arb_override_reason'))}",
                        f"- Agent C 误判提示：{_clean_cell(match.get('agentc_mistake_hint'))}",
                    ]
                )
            )
        agentc_case_text = "\n\n".join(agentc_case_blocks) if agentc_case_blocks else "无错误案例。"
        
        error_lines = []
        for e in errors[:20]:
            reason_clean = e.get('reason', '无').replace('\n', ' ').replace('|', '｜')
            error_lines.append(
                f"| {e.get('match_num', '未知')} | {e.get('league', '未知')} | {e.get('home', '未知')} vs {e.get('away', '未知')} | "
                f"{e.get('actual_score', '未知')}({e.get('actual_nspf', '未知')}) | {e.get('pred_nspf', '暂无')} | "
                f"初{e.get('asian_start', '未知')}→即{e.get('asian_live', '未知')} | {reason_clean} |"
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

### 四维方向命中对比
| 维度 | 命中 | 错误 | 信息不足 |
|:---|:---|:---|:---|
{dim_summary_table}

### 四种方向结果对比（基于每场最后一次预测记录）
| 编号 | 对阵 | 实际赛果 | 基本面 | 盘赔 | 情报 | 微观规则 | AgentC最终 |
|:---|:---|:---|:---|:---|:---|:---|:---|
{comparison_table}

### 错误案例清单（不让球预测与实际赛果不符）
| 编号 | 联赛 | 对阵 | 赛果 | AI预测 | 盘口变化 | 预测逻辑简述 |
|:---|:---|:---|:---|:---|:---|:---|
{error_table}

### Agent C 误判重点案例
{agentc_case_text}
"""
        
        prompt = f"""你是竞彩风控分析师。以下数据已经由程序精确计算，请仅基于这些数据进行分析。

{context}

你的任务：
1. **先比较四维方向，不要跳过结构化证据**：先基于“四维方向命中对比”与“每场四种方向结果对比”，明确四个维度谁更接近真实赛果、谁更容易偏掉、谁经常信息不足。
2. **重点拆解 Agent C 为什么错判**：围绕“Agent C 误判重点案例”，逐场说明：
   - 哪个维度本来更接近赛果；
   - Agent C 最终为什么没有跟随更接近赛果的维度；
   - 错在证据优先级、推翻链路、盘口理解，还是把弱证据当成强证据。
3. **盘口分析依然优先**：在解释 Agent C 错判时，主轴仍然必须落到盘口调度与盘口解释错在哪里，而不是泛泛总结基本面。
4. **深挖盘口调度失误（核心）**：围绕错误案例中的“初盘→即时盘”变化，明确指出系统在哪一步判断错了，例如：
   - 把真实阻上误判成诱上；
   - 把退盘控热误判成实力走弱；
   - 把升盘升水/退盘升水的资金含义读反；
   - 忽略欧赔实力方与亚赔让球方分工；
   - 该触发的微观信号没有触发，或触发了错误信号。
5. **归纳可复用的盘口错误模式**：总结这些错误属于哪几类固定盘口剧本，明确“以后遇到什么盘型/水位/欧亚组合必须警惕什么”。
6. **产出可回灌规则（最多3条）**：每条建议都必须尽量写成可落到微观信号规则库的形式，明确“触发条件 + 应对动作/防范方向”。
7. **逐场盘口复盘必须完整**：对于每一场错误案例，你必须单独保留该比赛编号的小节，并在该小节中明确写出以下 3 项：
   - `盘口链路`：必须落到初盘、即时盘、升降盘或水位变化，不能只写泛化结论；
   - `规则命中检查`：说明命中了哪些已有规则，或明确写“无规则命中”；
   - `规则处置建议`：必须在 `optimize_existing / add_new_rule / observe_only` 三者中三选一；若因为信息不足导致盘口链路不完整，必须明确写出 `missing_market_review`。
8. **重点回答是修旧规则还是补新规则**：
   - 若错误来自已有规则误用，必须明确说明是“完全背离”还是“边界过宽”，并优先给出 `optimize_existing`；
   - 若错误来自现有规则覆盖空白，给出 `add_new_rule`；
   - 若证据不足以立规，给出 `observe_only`，不能强行编规则。

严格约束：
- 严禁捏造任何不在此报告中的数据、比分或预测内容
- 胜=主队胜、负=主队负。严禁将"平/胜"说成"看好客队"
- 如果某场错误表显示预测为"胜(60%)/平(40%)"而赛果是"负"，你只能说"模型预测主队不败但主队输了"
- 基本面只能作为辅助说明，除非它能解释为什么盘口判断失效；否则不要喧宾夺主
- 输出用Markdown，分为"四维方向对比总览"、"Agent C误判链路"、"盘口调度错因拆解"、"微观信号修正规则"四部分
- 所有错误场次都必须在正文里被点名；不能跳过任何一场错误比赛
- 对每个错误场次，若你没有足够盘口链路，请显式写出 `missing_market_review`，禁止用一句泛化判断带过
"""
        if return_rule_drafts:
            prompt += """

附加输出要求：
- 在正文最后先追加一个标题为“## 结构化盘口复盘映射”的区块
- 该区块下面必须紧跟一个 ```json 代码块
- JSON 顶层必须是数组，数组中的每一项对应一个错误场次，字段必须包含：
  - case_id
  - match_num
  - matchup
  - market_chain_summary
  - misread_type
  - triggered_existing_rules
  - disposition
  - based_on_rule_id
  - recommended_target_scope
  - recommended_title
  - market_review_complete
  - entry_summary
- 在正文最后追加一个标题为“## 结构化规则草稿”的区块
- 该区块下面必须紧跟一个 ```json 代码块
- JSON 顶层必须是数组，最多输出 3 条规则草稿
- 每条草稿必须包含字段：
  - case_id
  - draft_id
  - title
  - target_scope（warning / micro_signal / arbitration_guard）
  - problem_type
  - trigger_condition_nl
  - suggested_condition
  - suggested_action
  - suggested_bias
  - priority
  - source_matches
  - disposition
  - based_on_rule_id
  - market_review_complete
  - status
  - created_at
- `suggested_condition` 必须是当前系统可直接执行的 Python 布尔表达式，不允许输出伪代码或自然语言 DSL
- 如果 `target_scope = micro_signal`，`suggested_condition` 只能使用以下上下文变量：
  - `asian['start_hv']`
  - `asian['live_hv']`
  - `asian['giving_start_w']`
  - `asian['receiving_start_w']`
  - `asian['giving_live_w']`
  - `asian['receiving_live_w']`
  - `euro['p_home']`
  - `euro['p_draw']`
  - `euro['p_away']`
  - `euro['live_home']`
  - `euro['live_draw']`
  - `euro['live_away']`
  - `euro['macau_start']`
  - `euro['bet365_start']`
  - `league['is_euro_cup']`
- 如果 `target_scope = arbitration_guard` 或 `warning`，`suggested_condition` 只能使用 `ctx[...]` 形式的上下文变量
- 严禁输出这些不兼容写法：`AND`、`OR`、`BETWEEN`、`IS TRUE`、`signal(...)`、`count(...)`、`all(...)`、`dimension.status`
- `disposition` 只能填写 `optimize_existing`、`add_new_rule`、`observe_only`
- 如果 `disposition = optimize_existing`，必须填写 `based_on_rule_id`
- `market_review_complete` 必须是布尔值；若该场盘口链路不完整，必须填 `false`
- 结构化盘口复盘映射 与 结构化规则草稿 必须一致：同一 `case_id` 的处置类型、旧规则ID、目标范围不得互相冲突
- 如果没有合适草稿，也必须输出空数组 []
- 如果没有合适草稿，也必须输出空数组 []
- 除了这个 JSON 区块外，不要输出额外解释
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是数据驱动的竞彩风控分析师。只基于提供的数据进行分析，严禁编造任何不在数据中的信息。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=5000
            )
            review_text = response.choices[0].message.content
            case_mappings = []
            rule_drafts = []
            if return_rule_drafts:
                review_text, case_mappings, rule_drafts = self._extract_review_structured_payloads(review_text)
                rendered_entries = self._render_market_review_entries(case_mappings)
                if rendered_entries:
                    review_text = (review_text.rstrip() + "\n\n" + rendered_entries).strip()
            is_valid, warnings = self.validate_review(review_text, accuracy_report)
            review_text = self._append_review_validation_section(review_text, warnings)
            
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
            final_review_text = header + review_text
            if return_rule_drafts:
                return final_review_text, rule_drafts, case_mappings
            return final_review_text
        except Exception as e:
            logger.error(f"调用LLM生成复盘报告异常: {e}")
            error_text = "生成复盘报告失败，请稍后重试。"
            return (error_text, []) if return_rule_drafts else error_text

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

        for match in errors:
            match_num = str(match.get("match_num") or "").strip()
            if not match_num:
                continue
            idx = review_text.find(match_num)
            if idx == -1:
                warnings.append(f"{match_num} 未在复盘正文中单独点名，存在逐场复盘缺失。")
                continue

            chunk = review_text[idx : idx + 700]
            has_market_chain = (
                ("初盘" in chunk and ("即时盘" in chunk or "终盘" in chunk or "退盘" in chunk or "升盘" in chunk))
                or "初盘→即时盘" in chunk
                or "盘口链路" in chunk
            )
            has_rule_check = (
                "规则命中" in chunk
                or "命中" in chunk
                or "无规则命中" in chunk
                or "half_ball_water_drop_no_rise" in chunk
            )
            has_disposition = any(
                token in chunk
                for token in [
                    "optimize_existing",
                    "add_new_rule",
                    "observe_only",
                    "missing_market_review",
                    "优化旧规则",
                    "新增规则",
                    "观察",
                ]
            )

            if not has_market_chain:
                warnings.append(f"{match_num} 盘口复盘缺失：未看到完整的初盘/即时盘/升降盘链路。")
            if not has_rule_check:
                warnings.append(f"{match_num} 规则命中检查缺失：未明确说明命中了哪些已有规则或是否无规则命中。")
            if not has_disposition:
                warnings.append(f"{match_num} 规则处置建议缺失：未明确说明优化旧规则、新增规则或仅观察。")

        return len(warnings) == 0, warnings

    @staticmethod
    def _build_agent_c_guardrails(*, dynamic_rules, leisu_brief, formatted_data):
        sections = [
            "### 🔴 动态风控铁律 (本场比赛必须遵守)\n" + dynamic_rules.strip()
        ]

        if any(key in dynamic_rules for key in ["浅盘升水诱下预警", "浅盘示弱诱下预警", "浅盘 (平半~半球)"]):
            sections.append(
                "### 🔴 去重执行口径\n"
                "对于浅盘场景，若上方同时出现“浅盘升水诱下预警”“浅盘示弱诱下预警”以及 `P1/DYNAMIC` 的相近规则：\n"
                "1. 一律先按 `P1` 中的浅盘专属规则定动作方向；\n"
                "2. `DYNAMIC_CHANGE_RULES` 只用于解释盘口为什么像“阻上/诱下/真实阻力”，不得把同一浅盘信号重复放大成多条独立结论；\n"
                "3. 最终在【盘赔深度解析】中应合并成一条清晰判断，不要把“升水、退盘、高水不退”拆成彼此冲突的多套结论。"
            )

        if any(key in leisu_brief for key in ["结构化伤停", "伤停摘要：核心缺阵约"]):
            sections.append(
                "### 🔴 结构化伤停引用硬约束\n"
                "如果上方“基本面摘要”中已经出现“结构化伤停”或“伤停摘要：核心缺阵约”，则你在【基本面剖析】中必须：\n"
                "1. 明确区分主队与客队的伤停影响；\n"
                "2. 至少引用 2 名具体球员或对应伤因；\n"
                "3. 禁止再使用“若属实”“数据存疑”“无法精准评估”等保守措辞；\n"
                "4. 直接说明这些伤停更偏向削弱哪一方的攻防环节。"
            )

        if "情报要点-" in leisu_brief or "情报要点-" in formatted_data:
            sections.append(
                "### 🔴 情报佐证硬约束\n"
                "如果上方输入中已经出现“情报要点-主队有利/不利、客队有利/不利、中立因素”，则你在【盘赔深度解析】中必须：\n"
                "1. 至少引用 2 条具体情报来解释盘口变化为何成立或为何与市场预期相反；\n"
                "2. 明确区分这些情报是在佐证让球方、受让方，还是欧赔实力方；\n"
                "3. 禁止只复述情报内容，必须落到“为什么机构会这样开盘/升降盘/控热”的解释上。"
            )

        if "市场锚点定义" in formatted_data:
            sections.append(
                "### 🔴 欧亚锚点硬约束\n"
                "如果“比赛原始数据参考”或“盘口专员报告”中已经出现“市场锚点定义”，则你在【盘赔深度解析】和【最终预测】中必须遵守：\n"
                "1. 亚赔只定义实际让球方/上盘，不得用竞彩让球方向覆盖；\n"
                "2. 欧赔只定义实力方/低赔保护方，可用于解释谁更强、谁更受市场防范；\n"
                "3. 若亚赔让球方与欧赔实力方不一致，必须明确写出“这是欧亚分工，不是二选一覆盖”；\n"
                "4. 在判断不让球胜平负时，可以用欧赔实力方做强弱锚点；在判断让球推荐时，必须回到亚赔定义的让球方。"
            )

        sections.append(
            "### 🔴 Agent C 显式仲裁工作流\n"
            "在输出【核心风控提示】和【最终预测】之前，你必须先完成【四维仲裁】。\n"
            "顺序固定为：1. 基本面方向；2. 盘赔方向；3. 情报佐证结论；4. 微观规则结论；5. 最终仲裁方向；6. 推翻原因。\n"
            "若四维之间存在冲突，必须明确写出“谁支持谁、谁压制谁、谁最终推翻谁”；若不存在明显冲突，才能写“无明显冲突，无需推翻”。"
        )

        return "\n\n".join(sections)

    @staticmethod
    def _extract_structured_block(text, block_name):
        import re

        if not text:
            return {}
        pattern = rf"\[{block_name}\]\s*(.*?)\s*\[/{block_name}\]"
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return {}
        body = match.group(1).strip()
        result = {}
        for line in body.splitlines():
            line = line.strip().lstrip("- ").strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
        return result

    @classmethod
    def _build_agent_structured_summaries(cls, agent_a_conclusion, agent_b_conclusion):
        summary_a = cls._extract_structured_block(agent_a_conclusion, "A_STRUCTURED")
        summary_b = cls._extract_structured_block(agent_b_conclusion, "B_STRUCTURED")

        lines = ["### 专员结构化摘要（内部仲裁输入）"]
        if summary_a:
            lines.append("- Agent A 结构化摘要：")
            lines.append(f"  - fundamental_side = {summary_a.get('fundamental_side', '未提取')}")
            lines.append(f"  - motivation_bias = {summary_a.get('motivation_bias', '未提取')}")
            lines.append(f"  - injury_bias = {summary_a.get('injury_bias', '未提取')}")
            lines.append(f"  - intel_bias = {summary_a.get('intel_bias', '未提取')}")
            lines.append(f"  - nspf_tilt = {summary_a.get('nspf_tilt', '未提取')}")
        else:
            lines.append("- Agent A 结构化摘要：未提取到，需优先参考正文。")

        if summary_b:
            lines.append("- Agent B 结构化摘要：")
            lines.append(f"  - market_side = {summary_b.get('market_side', '未提取')}")
            lines.append(f"  - market_intent = {summary_b.get('market_intent', '未提取')}")
            lines.append(f"  - intel_support = {summary_b.get('intel_support', '未提取')}")
            lines.append(f"  - micro_bias = {summary_b.get('micro_bias', '未提取')}")
            lines.append(f"  - nspf_tilt = {summary_b.get('nspf_tilt', '未提取')}")
        else:
            lines.append("- Agent B 结构化摘要：未提取到，需优先参考正文。")

        lines.append("- 使用方式：四维仲裁时先参考上述方向字段，再回看专员正文核验依据；若结构化摘要与正文冲突，以正文证据链更完整的一侧为准，并在推翻原因中说明。")
        return "\n".join(lines)

    @staticmethod
    def _normalize_tilt_tokens(value):
        text = (value or "").replace("/", "").replace("、", "").replace(" ", "")
        order = ["胜", "平", "负"]
        return [token for token in order if token in text]

    @classmethod
    def _compare_tilt_relation(cls, left_value, right_value):
        left = set(cls._normalize_tilt_tokens(left_value))
        right = set(cls._normalize_tilt_tokens(right_value))
        if not left or not right:
            return "信息不足"
        if left == right:
            return "完全一致"
        if len(left) == 2 and len(right) == 2 and len(left | right) == 3:
            return "明显冲突"
        if left & right:
            return "部分一致"
        return "明显冲突"

    @classmethod
    def _evaluate_conflict_matrix(
        cls,
        *,
        agent_a_conclusion,
        agent_b_conclusion,
        has_anchor_divergence=False,
        triggered_rule_ids=None,
    ):
        summary_a = cls._extract_structured_block(agent_a_conclusion, "A_STRUCTURED")
        summary_b = cls._extract_structured_block(agent_b_conclusion, "B_STRUCTURED")
        triggered_rule_ids = triggered_rule_ids or []

        fundamental_tilt = summary_a.get("nspf_tilt", "")
        market_tilt = summary_b.get("nspf_tilt", "")
        tilt_relation = cls._compare_tilt_relation(fundamental_tilt, market_tilt)
        intel_support = summary_b.get("intel_support", "") or summary_a.get("intel_bias", "")
        market_intent = summary_b.get("market_intent", "")
        micro_bias = summary_b.get("micro_bias", "")

        if intel_support:
            if any(keyword in intel_support for keyword in ["情报分裂", "情报不足"]):
                intel_relation = "情报本身不足以稳定支持某一边"
            elif "支持" in intel_support:
                intel_relation = f"情报当前更偏向：{intel_support}"
            else:
                intel_relation = intel_support
        else:
            intel_relation = "信息不足"

        if micro_bias:
            micro_relation = f"盘口意图={market_intent or '未提取'}；微观偏向={micro_bias}"
        elif triggered_rule_ids:
            micro_relation = f"已命中 {', '.join(f'[{rid}]' for rid in triggered_rule_ids)}，但盘口专员未结构化总结偏向"
        else:
            micro_relation = "无盘赔微观信号规则匹配或未形成明确偏向"

        conflict_flags = 0
        conflict_points = []
        if tilt_relation == "明显冲突":
            conflict_flags += 1
            conflict_points.append(
                f"基本面倾向={fundamental_tilt or '未提取'}，盘口倾向={market_tilt or '未提取'}，二者结构化方向明显冲突"
            )
        if has_anchor_divergence:
            conflict_flags += 1
            conflict_points.append("欧亚锚点存在分工背离，盘口方向与强弱锚点可能错位")
        if intel_support and "情报分裂" in intel_support:
            conflict_flags += 1
            conflict_points.append("情报层出现“情报分裂”，不足以稳定支持某一边")
        if micro_bias and market_intent and micro_bias not in ["无微观偏向"] and market_intent not in ["中性"]:
            if ("不胜" in micro_bias and market_intent in ["阻上", "真实阻力"]) or ("不败" in micro_bias and market_intent == "诱下"):
                conflict_flags += 1
                conflict_points.append(
                    f"盘口意图={market_intent}，但微观偏向={micro_bias}，二者在风险方向上存在反向信号"
                )

        if conflict_flags >= 2:
            severity = "high"
            verdict = "当前至少存在两处高冲突证据，最终仲裁必须明确写出谁推翻了谁，禁止写成“无明显冲突”。"
        elif conflict_flags == 1:
            severity = "medium"
            verdict = "当前存在一处关键冲突，需在【四维仲裁】里点名解释冲突来源。"
        else:
            severity = "low"
            verdict = "当前结构化层面未见强冲突，但仍需回看正文证据链防止误判。"

        return {
            "fundamental_tilt": fundamental_tilt or "未提取",
            "market_tilt": market_tilt or "未提取",
            "tilt_relation": tilt_relation,
            "intel_relation": intel_relation,
            "micro_relation": micro_relation,
            "anchor_relation": "欧亚存在分工背离，需警惕盘口与强弱锚点错位" if has_anchor_divergence else "欧亚锚点未见明显背离",
            "conflict_flags": conflict_flags,
            "conflict_points": conflict_points,
            "severity": severity,
            "verdict": verdict,
        }

    @classmethod
    def _build_conflict_matrix_hint(
        cls,
        *,
        agent_a_conclusion,
        agent_b_conclusion,
        has_anchor_divergence=False,
        triggered_rule_ids=None,
    ):
        assessment = cls._evaluate_conflict_matrix(
            agent_a_conclusion=agent_a_conclusion,
            agent_b_conclusion=agent_b_conclusion,
            has_anchor_divergence=has_anchor_divergence,
            triggered_rule_ids=triggered_rule_ids,
        )

        lines = ["### 四维冲突矩阵（内部仲裁提示）"]
        lines.append(
            f"- 基本面倾向 vs 盘口倾向：{assessment['fundamental_tilt']} vs {assessment['market_tilt']} -> {assessment['tilt_relation']}"
        )
        lines.append(f"- 情报佐证 vs 盘口方向：{assessment['intel_relation']}")
        lines.append(f"- 微观规则 vs 盘口意图：{assessment['micro_relation']}")
        lines.append(f"- 欧亚锚点 vs 盘口方向：{assessment['anchor_relation']}")

        lines.append(f"- 仲裁提示：{assessment['verdict']}")

        return "\n".join(lines)

    def _build_programmatic_arbitration_hint(
        self,
        *,
        match_data,
        risk_policy,
        triggered_rule_ids,
        micro_signals_text,
        odds_conflict_text="",
        has_anchor_divergence=False,
    ):
        market_anchor = self._build_market_anchor_summary(match_data)
        asian_anchor = market_anchor.get("asian", {})
        euro_anchor = market_anchor.get("euro", {})

        lines = [
            "### 程序化仲裁参考（只作为裁决证据，不直接等同最终结论）",
            f"- 亚赔实际让球方：{asian_anchor.get('label', '未明确')}（{asian_anchor.get('basis', '无依据')}）",
            f"- 欧赔实力方：{euro_anchor.get('label', '未明确')}（{euro_anchor.get('basis', '无依据')}）",
            f"- 欧亚是否分工背离：{'是' if has_anchor_divergence else '否'}",
        ]

        if triggered_rule_ids:
            lines.append(f"- 微观规则命中：{', '.join(f'[{rid}]' for rid in triggered_rule_ids)}")
        else:
            lines.append("- 微观规则命中：无盘赔微观信号规则匹配")

        confidence_cap = risk_policy.get("confidence_cap")
        if confidence_cap is not None:
            lines.append(f"- 程序侧风险上限：竞彩置信度不得高于 {confidence_cap}")

        if odds_conflict_text:
            conflict_summary = str(odds_conflict_text).strip().replace("\n", " | ")
            lines.append(f"- 赔率冲突摘要：{conflict_summary[:280]}")

        injuries_text = (match_data.get("injuries_detailed") or {}).get("injuries_text", "")
        if injuries_text:
            parsed_injuries = self._parse_leisu_injuries(injuries_text)
            if parsed_injuries.get("valid"):
                lines.append(f"- 伤停量化摘要：核心缺阵约 {parsed_injuries.get('core_count')} 人")
                structured = self._format_structured_leisu_injuries(match_data)
                if structured.get("valid"):
                    first_structured_line = structured["text"].split("\n")[0].strip()
                    if first_structured_line:
                        lines.append(f"- 伤停结构化参考：{first_structured_line}")

        intel = match_data.get("leisu_intelligence") or {}
        if isinstance(intel, dict):
            home = intel.get("home") or {}
            away = intel.get("away") or {}
            neutral = intel.get("neutral") or []
            lines.append(
                f"- 情报数量分布：主队有利{len(home.get('pros') or [])}条 / 主队不利{len(home.get('cons') or [])}条 / "
                f"客队有利{len(away.get('pros') or [])}条 / 客队不利{len(away.get('cons') or [])}条 / 中立{len(neutral)}条"
            )

        if micro_signals_text:
            first_micro = next((line.strip() for line in micro_signals_text.splitlines() if line.strip()), "")
            if first_micro:
                lines.append(f"- 微观规则摘要：{first_micro}")

        lines.append("- 使用方式：请先完成【四维仲裁】，再决定是否需要由基本面/情报推翻盘口方向；若要推翻，必须写清楚推翻链路。")
        return "\n".join(lines)

    def _build_agent_c_prompt(
        self,
        *,
        dynamic_rules,
        formatted_data,
        leisu_brief,
        leisu_intel_hint,
        agent_a_conclusion,
        agent_b_conclusion,
        programmatic_arbitration_hint,
        agent_structured_summaries,
        conflict_matrix_hint,
    ):
        guardrails = self._build_agent_c_guardrails(
            dynamic_rules=dynamic_rules,
            leisu_brief=leisu_brief,
            formatted_data=formatted_data,
        )
        return f"""
{AGENT_C_PROMPT}

{guardrails}

{programmatic_arbitration_hint}

{agent_structured_summaries}

{conflict_matrix_hint}

---
### 比赛原始数据参考
{formatted_data}

---
### 基本面补充摘要（如有，必须在【基本面剖析】中显式引用）
{leisu_brief}

---
### 情报归属提示（如有，必须在【盘赔深度解析】中落实）
{leisu_intel_hint}

---
### 专员报告
**【基本面专员报告】**：
{agent_a_conclusion}

**【盘口专员报告】**：
{agent_b_conclusion}

请根据以上报告和风控铁律，输出最终预测。
"""

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
            
            # 3. RAG 召回：从历史错题本中寻找相似教训
            similar_errors_warning = self._recall_similar_errors(match_data, handicap_label)
            if similar_errors_warning:
                dynamic_rules += f"\n\n{similar_errors_warning}"

            match_odds = match_data.get("odds", {}) or {}
            match_asian_odds = match_data.get("asian_odds", {}) or {}
            match_league = match_data.get("league", "") or ""
            match_euro_odds = match_data.get("europe_odds", []) or []
            market_anchor = self._build_market_anchor_summary(match_data)
            odds_conflict_text = self._detect_odds_conflict(match_odds, match_asian_odds, match_euro_odds)
            asian_anchor_side = market_anchor.get("asian", {}).get("side")
            euro_anchor_side = market_anchor.get("euro", {}).get("side")
            has_anchor_divergence = (
                asian_anchor_side is not None
                and euro_anchor_side is not None
                and asian_anchor_side != euro_anchor_side
            )
            micro_signals_text = self._analyze_micro_market_signals(match_odds, match_asian_odds, match_league, euro_odds=match_euro_odds)
            triggered_rule_ids = re.findall(r"\[(\w+)\]", micro_signals_text) if micro_signals_text else []
            risk_policy = self._build_risk_policy(
                triggered_rule_ids=triggered_rule_ids,
                odds_conflict_text=odds_conflict_text,
                has_anchor_divergence=has_anchor_divergence,
            )
            if micro_signals_text:
                micro_signal_block = "\n".join([f"- {line}" for line in micro_signals_text.split("\n") if line.strip()])
            else:
                micro_signal_block = "无"

            dynamic_rules += f"\n\n### 🧩 盘赔微观信号触发清单（程序已判定）\n{micro_signal_block}\n"
            if triggered_rule_ids:
                dynamic_rules += (
                    "\n### 🔴 微观信号硬约束（触发即生效）\n"
                    "1) 在【盘赔深度解析】中必须逐条回应以上每条微观信号（必须引用对应的 [rule_id]）。\n"
                    "2) **竞彩推荐**与**竞彩让球推荐**必须双选（绝对禁止单选）。\n"
                    "3) **竞彩置信度上限 65**；若你认为可以更高，必须明确说明你如何推翻这些微观信号。\n"
                )
            
            # ==========================================
            # Agent A: 基本面专员 (仅看基本面数据)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent A 正在分析基本面...")
            agent_a_data = self._extract_fundamentals(match_data)
            agent_a_response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": AGENT_A_PROMPT},
                    {"role": "user", "content": f"请分析以下比赛的基本面：\n{agent_a_data}"}
                ],
                temperature=0.3
            )
            agent_a_conclusion = agent_a_response.choices[0].message.content
            agent_a_structured = self._extract_structured_block(agent_a_conclusion, "A_STRUCTURED")
            
            # ==========================================
            # Agent B: 盘口推演专员 (仅看盘口与预警数据)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent B 正在推演盘口意图...")
            agent_b_data = self._extract_odds_data(match_data)
            agent_b_response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": AGENT_B_PROMPT},
                    {"role": "user", "content": f"请推演以下比赛的机构盘口意图：\n{agent_b_data}"}
                ],
                temperature=0.4
            )
            agent_b_conclusion = agent_b_response.choices[0].message.content
            agent_b_structured = self._extract_structured_block(agent_b_conclusion, "B_STRUCTURED")
            
            # ==========================================
            # Agent C: 风控裁判长 (整合输出)
            # ==========================================
            logger.info(f"[{match_data.get('home_team')} vs {match_data.get('away_team')}] Agent C 正在进行最终风控裁决...")
            leisu_brief = self._format_leisu_brief(match_data)
            leisu_intel_hint = self._build_leisu_intel_anchor_hint(match_data)
            programmatic_arbitration_hint = self._build_programmatic_arbitration_hint(
                match_data=match_data,
                risk_policy=risk_policy,
                triggered_rule_ids=triggered_rule_ids,
                micro_signals_text=micro_signals_text,
                odds_conflict_text=odds_conflict_text,
                has_anchor_divergence=has_anchor_divergence,
            )
            agent_structured_summaries = self._build_agent_structured_summaries(
                agent_a_conclusion=agent_a_conclusion,
                agent_b_conclusion=agent_b_conclusion,
            )
            conflict_matrix_hint = self._build_conflict_matrix_hint(
                agent_a_conclusion=agent_a_conclusion,
                agent_b_conclusion=agent_b_conclusion,
                has_anchor_divergence=has_anchor_divergence,
                triggered_rule_ids=triggered_rule_ids,
            )
            conflict_assessment = self._evaluate_conflict_matrix(
                agent_a_conclusion=agent_a_conclusion,
                agent_b_conclusion=agent_b_conclusion,
                has_anchor_divergence=has_anchor_divergence,
                triggered_rule_ids=triggered_rule_ids,
            )
            final_prompt = self._build_agent_c_prompt(
                dynamic_rules=dynamic_rules,
                formatted_data=formatted_data,
                leisu_brief=leisu_brief,
                leisu_intel_hint=leisu_intel_hint,
                agent_a_conclusion=agent_a_conclusion,
                agent_b_conclusion=agent_b_conclusion,
                programmatic_arbitration_hint=programmatic_arbitration_hint,
                agent_structured_summaries=agent_structured_summaries,
                conflict_matrix_hint=conflict_matrix_hint,
            )
            agent_c_response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": final_prompt}
                ],
                temperature=0.2 # 裁判长需要极其冷静客观
            )
            
            result = agent_c_response.choices[0].message.content

            details = self.parse_prediction_details(result)
            arbitration_ctx = self._build_arbitration_rule_context(
                details=details,
                conflict_assessment=conflict_assessment,
                triggered_rule_ids=triggered_rule_ids,
                asian_context=self._build_micro_rule_asian_context(match_asian_odds),
            )
            arbitration_actions = self._evaluate_arbitration_rules(arbitration_ctx)
            retry_msgs = self._build_retry_messages(
                result_text=result,
                details=details,
                risk_policy=risk_policy,
                match_asian_odds=match_asian_odds,
                triggered_rule_ids=triggered_rule_ids,
                match_data=match_data,
                conflict_assessment=conflict_assessment,
            )
            if arbitration_actions.get("override_blocked") and arbitration_ctx.get("reverse_only_from_fundamental_or_intel"):
                retry_msgs.append(
                    "当前命中仲裁保护规则：当盘赔与微观规则同向时，不得仅凭基本面或情报单独推翻市场方向。请重新核验【最终仲裁方向】与【推翻原因】。"
                )

            if retry_msgs:
                logger.warning("检测到推理链路存在冲突，触发一次复核重试")
                numbered = "\n".join([f"{i+1}) {msg}" for i, msg in enumerate(retry_msgs)])
                retry_prompt = final_prompt + f"""

### 🔴 复核问题清单（请逐条核验并重写相关依据）
{numbered}

请重新输出最终预测，其余输出格式必须与原 Output Format 完全一致。
"""
                agent_c_retry = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": retry_prompt}],
                    temperature=0.1,
                )
                result = agent_c_retry.choices[0].message.content

            final_details = self.parse_prediction_details(result)
            final_arbitration_ctx = self._build_arbitration_rule_context(
                details=final_details,
                conflict_assessment=conflict_assessment,
                triggered_rule_ids=triggered_rule_ids,
                asian_context=self._build_micro_rule_asian_context(match_asian_odds),
            )
            final_arbitration_actions = self._evaluate_arbitration_rules(final_arbitration_ctx)
            effective_risk_policy = dict(risk_policy)
            if final_arbitration_actions.get("must_double_nspf"):
                effective_risk_policy["must_double_nspf"] = True
            if final_arbitration_actions.get("must_double_rq"):
                effective_risk_policy["must_double_rq"] = True
            arb_confidence_cap = final_arbitration_actions.get("confidence_cap")
            if arb_confidence_cap is not None:
                current_cap = effective_risk_policy.get("confidence_cap")
                effective_risk_policy["confidence_cap"] = (
                    arb_confidence_cap if current_cap is None else min(current_cap, arb_confidence_cap)
                )

            result, arbitration_changed = self._apply_arbitration_actions(
                result,
                final_details,
                final_arbitration_actions,
            )
            if arbitration_changed:
                logger.warning("已根据仲裁保护规则对最终输出执行边界约束")
                final_details = self.parse_prediction_details(result)

            coverage_changed = False
            if not final_arbitration_actions.get("abort_prediction"):
                result, coverage_changed = self._enforce_minimum_risk_coverage(
                    result,
                    final_details,
                    effective_risk_policy,
                    match_asian_odds,
                )
                if coverage_changed:
                    logger.warning("纠错后仍未满足最小风险覆盖，已执行代码级双选兜底")
                    final_details = self.parse_prediction_details(result)

            final_conf_val = self._parse_conf_int(final_details.get("confidence", ""))
            confidence_cap = effective_risk_policy.get("confidence_cap")
            if confidence_cap is not None and final_conf_val is not None and final_conf_val > confidence_cap:
                result, changed = self._clamp_confidence_line(result, confidence_cap)
                if changed:
                    logger.warning(f"纠错后仍超出置信度上限，已执行代码级兜底钳制到{confidence_cap}")

            logger.info(f"预测成功返回！ [时间段: {period}]")
            return result, period
            
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            return f"预测失败: {e}", period

    def _format_leisu_brief(self, match_data):
        parts = []
        injuries_text = (match_data.get("injuries_detailed") or {}).get("injuries_text", "")
        if injuries_text:
            parsed = self._parse_leisu_injuries(injuries_text)
            if parsed["valid"]:
                structured = self._format_structured_leisu_injuries(match_data)
                parts.append(f"- 伤停摘要：核心缺阵约 {parsed['core_count']} 人")
                if structured["valid"]:
                    for line in structured["text"].split("\n"):
                        parts.append(f"- 结构化伤停：{line}")
                else:
                    parts.append(f"- 伤停明细：{parsed['text'][:260]}")
            else:
                parts.append(f"- 伤停摘要：明细疑似乱码/无效（{parsed['reason']}），已跳过量化")

        standings_info = match_data.get("standings_info", [])
        if standings_info:
            parts.append(f"- 排名参考：{standings_info}")

        h2h_leisu = match_data.get("h2h_leisu", [])
        if h2h_leisu:
            parts.append(f"- 交锋比分：{h2h_leisu[:6]}")

        recent_leisu = match_data.get("recent_leisu", [])
        if recent_leisu:
            parts.append(f"- 近期比分：{recent_leisu[:6]}")

        goal_dist = match_data.get("goal_distribution", [])
        if goal_dist and isinstance(goal_dist, list):
            parts.append(f"- 进球分布：{goal_dist[:18]}")

        parts.extend(self._format_leisu_intelligence_block(match_data))

        return "\n".join(parts) if parts else "暂无"

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

        injuries_detailed = match_data.get('injuries_detailed', {})
        injuries_text = (injuries_detailed or {}).get('injuries_text', '')
        if injuries_text:
            parsed = self._parse_leisu_injuries(injuries_text)
            if parsed["valid"]:
                info += f"- 伤停摘要（量化）：核心缺阵约 {parsed['core_count']} 人\n"
                structured = self._format_structured_leisu_injuries(match_data)
                if structured["valid"]:
                    for line in structured["text"].split("\n"):
                        info += f"- 结构化伤停：{line}\n"
                else:
                    info += f"- 伤停明细：{parsed['text'][:500]}\n"
            else:
                info += f"- 伤停摘要：明细疑似乱码/无效（{parsed['reason']}），跳过量化\n"

        standings_info = match_data.get('standings_info', [])
        if standings_info:
            info += f"- 联赛排名参考：{standings_info}\n"

        h2h_leisu = match_data.get('h2h_leisu', [])
        if h2h_leisu:
            info += f"- 历史交锋比分参考：{h2h_leisu[:6]}\n"

        recent_leisu = match_data.get('recent_leisu', [])
        if recent_leisu:
            info += f"- 近期战绩比分参考：{recent_leisu[:6]}\n"

        for line in self._format_leisu_intelligence_block(match_data):
            info += f"{line}\n"

        goal_dist = match_data.get('goal_distribution', [])
        if goal_dist and isinstance(goal_dist, list):
            info += f"- 进球时间分布参考：{goal_dist[:18]}\n"
            
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
        market_anchor = self._build_market_anchor_summary(match_data)
        info += f"- 🔎 市场锚点定义：{market_anchor['text']}\n"
        if odds.get('nspf'):
            info += f"- 竞彩不让球赔率：{odds.get('nspf', [])}\n"
        if odds.get('spf'):
            info += f"- 竞彩让球({odds.get('rangqiu')})赔率：{odds.get('spf', [])}\n"
            
        asian = match_data.get('asian_odds', {})
        if 'macau' in asian:
            info += f"- 澳门亚指：初盘 [{asian['macau'].get('start')}] -> 即时盘 [{asian['macau'].get('live')}]\n"

        for line in self._format_leisu_intelligence_block(match_data):
            info += f"{line}\n"

        micro_signals = self._analyze_micro_market_signals(odds, asian, match_data.get("league", ""), euro_odds=match_data.get("europe_odds", []))
        if micro_signals:
            info += f"- 🧩 盘赔微观信号：\n"
            for line in micro_signals.split("\n"):
                if line.strip():
                    info += f"  - {self._format_signal_with_prediction_bias(line, asian)}\n"
            
        # 加入量化预警
        deep_water = self._detect_deep_water_trap(asian)
        if deep_water: info += f"- 🚨 超深盘死水预警：{self._format_signal_with_prediction_bias(deep_water, asian)}\n"
        
        half_ball = self._detect_half_ball_trap(asian, odds)
        if half_ball: info += f"- 🔴 半球生死盘预警：{self._format_signal_with_prediction_bias(half_ball, asian)}\n"
        
        divergence = self._detect_handicap_water_divergence(asian)
        if divergence: info += f"- 🔴 盘水背离预警：{self._format_signal_with_prediction_bias(divergence, asian)}\n"
        
        shallow_water = self._detect_shallow_water_trap(asian, odds)
        if shallow_water: info += f"- 🔴 浅盘升水诱下预警：{self._format_signal_with_prediction_bias(shallow_water, asian)}\n"
        
        euro_asian = self._detect_euro_asian_divergence(odds, asian, match_data.get('europe_odds', []))
        if euro_asian: info += f"- 🚨 欧亚背离量化预警：{self._format_signal_with_prediction_bias(euro_asian, asian)}\n"

        shallow_showweak = self._detect_shallow_showweak_induce_down(asian)
        if shallow_showweak: info += f"- 🔴 浅盘示弱诱下预警：{self._format_signal_with_prediction_bias(shallow_showweak, asian)}\n"
        
        return info

    @staticmethod
    def _analyze_micro_market_signals(odds, asian, league, euro_odds=None):
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
            parts = (line or "").split('|')
            if len(parts) < 3:
                return None
            try:
                w1 = float(parts[0].strip().replace('↑', '').replace('↓', ''))
                h = parts[1].strip().replace(' ', '')
                w2 = float(parts[2].strip().replace('↑', '').replace('↓', ''))
                hv = handicap_map.get(h, None)
                if hv is None:
                    return None
                return {"w1": w1, "h": h, "hv": hv, "w2": w2}
            except Exception:
                return None

        def implied_probs_from_nspf(nspf):
            if not nspf or len(nspf) != 3:
                return None
            try:
                home_odds = float(nspf[0])
                draw_odds = float(nspf[1])
                away_odds = float(nspf[2])
                implied_prob_sum = (1 / home_odds) + (1 / draw_odds) + (1 / away_odds)
                return_rate = 1 / implied_prob_sum
                return ((1 / home_odds) * return_rate, (1 / draw_odds) * return_rate, (1 / away_odds) * return_rate)
            except Exception:
                return None

        macau = asian.get("macau", {})
        s = parse(macau.get("start", ""))
        l = parse(macau.get("live", ""))
        if not s or not l:
            return ""

        hs, hl = s["hv"], l["hv"]
        giving_start_w = s["w1"] if hs >= 0 else s["w2"]
        receiving_start_w = s["w2"] if hs >= 0 else s["w1"]
        giving_live_w = l["w1"] if hl >= 0 else l["w2"]
        receiving_live_w = l["w2"] if hl >= 0 else l["w1"]

        probs = implied_probs_from_nspf((odds or {}).get("nspf", []))
        p_home, p_draw, p_away = probs if probs else (None, None, None)

        is_euro_cup = any(k in (league or "") for k in ["欧协联", "欧联", "欧冠"])

        nspf_odds = (odds or {}).get("nspf", [])
        live_home = float(nspf_odds[0]) if len(nspf_odds) == 3 else None
        live_draw = float(nspf_odds[1]) if len(nspf_odds) == 3 else None
        live_away = float(nspf_odds[2]) if len(nspf_odds) == 3 else None
        
        # 提取欧洲赔率 (初盘)
        macau_start = None
        bet365_start = None
        if euro_odds:
            for item in euro_odds:
                company = item.get('company', '')
                try:
                    if '澳门' in company:
                        macau_start = {
                            'h': float(item.get('init_home', 0)),
                            'd': float(item.get('init_draw', 0)),
                            'a': float(item.get('init_away', 0))
                        }
                    elif 'bet365' in company.lower():
                        bet365_start = {
                            'h': float(item.get('init_home', 0)),
                            'd': float(item.get('init_draw', 0)),
                            'a': float(item.get('init_away', 0))
                        }
                except (ValueError, TypeError):
                    continue

        # 1. 构造上下文 (Context)
        context = {
            "asian": {
                "start_hv": hs,
                "live_hv": hl,
                "giving_start_w": giving_start_w,
                "receiving_start_w": receiving_start_w,
                "giving_live_w": giving_live_w,
                "receiving_live_w": receiving_live_w,
            },
            "euro": {
                "p_home": p_home,
                "p_draw": p_draw,
                "p_away": p_away,
                "live_home": live_home,
                "live_draw": live_draw,
                "live_away": live_away,
                "macau_start": macau_start,
                "bet365_start": bet365_start
            },
            "league": {
                "is_euro_cup": is_euro_cup
            }
        }

        # 2. 读取外部规则并执行 (Evaluator)
        lines = []
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            rules_path = os.path.join(base_dir, "data", "rules", "micro_signals.json")
            if os.path.exists(rules_path):
                with open(rules_path, 'r', encoding='utf-8') as f:
                    rules = json.load(f)
                
                for rule in rules:
                    if not rule.get("enabled", True):
                        continue
                    
                    try:
                        # 执行条件表达式
                        is_triggered = simpleeval.simple_eval(rule["condition"], names=context, functions={"abs": abs, "min": min, "max": max})
                        if is_triggered:
                            # 渲染模板 (支持 {asian[live_hv]} 这种 f-string 语法)
                            msg = eval(f"f'''{rule['warning_template']}'''", context)
                            # 带上 rule_id 和名称，便于 Agent C 验证和报告中引用
                            rid = rule.get("id", "?")
                            rname = rule.get("name", "?")
                            rlevel = rule.get("level", "?")
                            full_text = f"{rlevel} [{rid}] {rname}：{msg}"
                            lines.append(LLMPredictor._format_signal_with_prediction_bias(full_text, asian))
                    except Exception as e:
                        logger.warning(f"执行规则 {rule.get('id')} 失败: {e}")
        except Exception as e:
            logger.warning(f"读取或执行动态微观信号规则失败: {e}")

        return "\n".join(lines)

    def _recall_similar_errors(self, match_data, current_handicap_label):
        """
        从本地错题本 (errors.json) 中召回高度相似的历史教训。
        匹配维度：同联赛 + 同盘口深度。
        """
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            error_db_dir = os.path.join(base_dir, 'data', 'knowledge_base', 'errors')
            
            if not os.path.exists(error_db_dir):
                return ""
                
            current_league = match_data.get('league', '')
            if not current_league or not current_handicap_label:
                return ""
                
            # 简化盘口标签用于模糊匹配 (如：平半, 半球, 一球)
            simplified_ht = current_handicap_label.split('(')[0].replace('受', '')
            
            similar_cases = []
            
            # 遍历最近的错题文件
            for filename in sorted(os.listdir(error_db_dir), reverse=True)[:10]: # 最多看最近10天的错题
                if not filename.endswith('.json'):
                    continue
                    
                with open(os.path.join(error_db_dir, filename), 'r', encoding='utf-8') as f:
                    errors = json.load(f)
                    
                for err in errors:
                    # 获取错题中的联赛和盘口
                    err_league = err.get('league', '') if 'league' in err else err.get('raw_data', {}).get('league', '')
                    err_asian = err.get('asian_start', '') if 'asian_start' in err else err.get('raw_data', {}).get('asian_odds', {}).get('macau', {}).get('start', '')
                    
                    if not err_league or not err_asian:
                        continue
                        
                    if current_league in err_league or err_league in current_league:
                        # 检查 simplified_ht (如"平半"或"平手半球") 是否在历史盘口文本中
                        # 兼容各种亚盘的称呼写法
                        if (simplified_ht in err_asian or err_asian in simplified_ht or 
                            simplified_ht in err_asian.replace('/', '') or
                            err_asian in simplified_ht.replace(' ', '')):
                            # 找到相似错题！
                            actual_res = err.get('actual_result', '') or f"{err.get('actual_nspf', '')}/{err.get('actual_spf', '')}"
                            reason = err.get('ai_reason', '') or err.get('reason', '')
                            
                            similar_cases.append(
                                f"- 赛事：【{err.get('home_team') or err.get('home')} vs {err.get('away_team') or err.get('away')}】\n"
                                f"  - 当时盘口：{err_asian}\n"
                                f"  - AI当时错误判断：{reason[:100]}...\n"
                                f"  - 最终真实赛果：{actual_res}（冷门打出）\n"
                            )
                            
                            if len(similar_cases) >= 2: # 最多给2个案例，防止Prompt过长
                                break
                
                if len(similar_cases) >= 2:
                    break
                    
            if similar_cases:
                warning_text = "### 🚨 历史错题召回警告 (RAG)\n"
                warning_text += f"系统在历史错题库中发现，在【{current_league}】联赛的【{simplified_ht}】盘口下，模型曾犯过以下错误。请你务必仔细比对当前比赛，**切勿重蹈覆辙，优先考虑防范冷门**：\n"
                warning_text += "\n".join(similar_cases)
                return warning_text
                
        except Exception as e:
            logger.error(f"召回历史错题失败: {e}")
            
        return ""

    @staticmethod
    def _parse_match_time_value(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value

        text = str(value).strip()
        if not text:
            return None

        normalized = text.replace("T", " ")
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
        ):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _determine_prediction_period(self, match_data):
        """
        根据比赛时间判断预测时间段
        :return: 'pre_24h', 'pre_12h', 'final'
        """
        try:
            match_time = self._parse_match_time_value(match_data.get("match_time"))
            if not match_time:
                return "pre_24h"

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

    @staticmethod
    def _parse_confidence_score(value):
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        match = re.search(r"\d+", str(value))
        return int(match.group()) if match else 0

    @staticmethod
    def _parse_float(value, default=0.0):
        try:
            return float(str(value).strip())
        except Exception:
            return default

    @staticmethod
    def _extract_recommendation_options(text):
        if not text or text in {"无", "暂无"}:
            return []
        cleaned = re.sub(r"\([^)]*\)", "", str(text))
        tokens = []
        for part in re.split(r"[\/,，+]", cleaned):
            token = part.strip()
            if token in {"胜", "平", "负", "让胜", "让平", "让负"}:
                tokens.append(token)
        return tokens

    @staticmethod
    def _extract_goals_options(text):
        if not text or text in {"无", "暂无"}:
            return []
        cleaned = str(text).replace("球", "").replace("、", "/").replace(",", "/").replace("，", "/")
        tokens = []
        if "7+" in cleaned:
            tokens.append("7+")
            cleaned = cleaned.replace("7+", "")
        for part in re.split(r"[\/\s]+", cleaned):
            token = part.strip()
            if token.isdigit() and token not in tokens:
                tokens.append(token)
        return tokens[:2]

    def _build_available_plays(self, match):
        nspf_options = self._extract_recommendation_options(
            match.get("竞彩推荐(不让球)") or match.get("竞彩推荐")
        )
        rq_options = self._extract_recommendation_options(match.get("竞彩让球推荐"))
        goals_options = self._extract_goals_options(match.get("AI预测进球数") or match.get("进球数参考"))
        nspf_odds = match.get("不让球赔率(胜/平/负)", []) or []
        rq_odds = match.get("让球赔率(胜/平/负)", []) or []
        confidence = self._parse_confidence_score(match.get("置信度") or match.get("胜平负置信度"))

        def build_entry(market, options, odds, label, index_map):
            if not options or len(odds) != 3:
                return None
            selected_odds = [self._parse_float(odds[index_map[option]]) for option in options if option in index_map]
            if not selected_odds:
                return None
            return {
                "market": market,
                "label": label,
                "selection": "/".join(options),
                "options": options,
                "odds": selected_odds,
                "min_odds": min(selected_odds),
                "max_odds": max(selected_odds),
                "options_count": len(options),
                "estimated": False,
            }

        plays = [
            build_entry("nspf", nspf_options, nspf_odds, "竞彩不让球", {"胜": 0, "平": 1, "负": 2}),
            build_entry(
                "rq",
                rq_options,
                rq_odds,
                f"竞彩让球({match.get('让球数', '0')})",
                {"让胜": 0, "让平": 1, "让负": 2},
            ),
        ]
        if goals_options:
            estimated_odds = [3.5 for _ in goals_options]
            plays.append({
                "market": "goals",
                "label": "进球数",
                "selection": "/".join(f"{option}球" if option != "7+" else "7+球" for option in goals_options),
                "options": goals_options,
                "odds": estimated_odds,
                "min_odds": min(estimated_odds),
                "max_odds": max(estimated_odds),
                "options_count": len(goals_options),
                "estimated": True,
            })
        return [play for play in plays if play]

    def _build_primary_play(self, match):
        plays = self._build_available_plays(match)
        if not plays:
            return None
        confidence = self._parse_confidence_score(match.get("置信度") or match.get("胜平负置信度"))

        plays.sort(
            key=lambda play: (
                play.get("estimated", False),
                play["options_count"] > 1,
                abs(play["max_odds"] - (1.85 if confidence >= 68 else 2.35)),
            )
        )
        return plays[0]

    def _score_parlay_candidate(self, match):
        confidence = self._parse_confidence_score(match.get("置信度") or match.get("胜平负置信度"))
        reason = str(match.get("基础理由", "") or "")
        available_plays = self._build_available_plays(match)
        primary_play = self._build_primary_play(match)

        stable = max(0, confidence - 55)
        value = max(0, confidence - 58)
        aggressive = max(0, confidence - 60)
        penalty = 0

        if primary_play:
            stable += 8
            value += 6
            if primary_play["options_count"] == 1:
                stable += 5
            else:
                value += 6
                aggressive += 4

            if 1.35 <= primary_play["max_odds"] <= 2.20:
                stable += 10
            if 1.70 <= primary_play["max_odds"] <= 3.20:
                value += 10
            if primary_play["max_odds"] >= 2.80:
                aggressive += 14
        else:
            penalty += 20

        if reason and reason != "无":
            stable += 6
            value += 5
            aggressive += 3
        else:
            penalty += 10

        if any(keyword in reason for keyword in ["冷", "平局", "受让", "阻上", "诱上", "爆冷", "高赔"]):
            aggressive += 8
            value += 4

        if confidence < 58:
            penalty += 18
        elif confidence < 63:
            penalty += 8

        if primary_play and primary_play["options_count"] > 1 and confidence >= 65:
            value += 4

        return {
            "stable": max(0, stable - penalty),
            "value": max(0, value - penalty),
            "aggressive": max(0, aggressive - penalty),
            "penalty": penalty,
        }, primary_play, available_plays

    @staticmethod
    def _build_candidate_annotations(confidence, reason, primary_play, scores):
        tags = []
        selection_reasons = []
        risk_notes = []

        if confidence >= 72:
            tags.append("稳胆候选")
            selection_reasons.append("置信度处于高位，可作为主推稳胆观察。")
        elif confidence >= 65:
            tags.append("平衡候选")
            selection_reasons.append("置信度达标，适合放入中倍平衡方案。")
        else:
            tags.append("利润候选")
            selection_reasons.append("置信度一般，更适合作为利润冲击位而非主推胆。")

        if primary_play:
            if primary_play["options_count"] == 1:
                tags.append("单选")
                selection_reasons.append("当前主玩法为单选，结构更利于稳健控制。")
            else:
                tags.append("双选")
                selection_reasons.append("当前主玩法为双选，具备一定容错与赔率弹性。")

            if 1.35 <= primary_play["max_odds"] <= 2.20:
                tags.append("稳健赔率")
                selection_reasons.append("赔率区间落在稳健盈利带内。")
            elif primary_play["max_odds"] >= 2.80:
                tags.append("高倍潜力")
                selection_reasons.append("赔率具备明显放大利润空间。")
                risk_notes.append("赔率较高，必须搭配稳胆锚点使用。")

        hot_keywords = ["冷", "平局", "受让", "阻上", "诱上", "爆冷", "高赔"]
        if any(keyword in reason for keyword in hot_keywords):
            tags.append("冷门逻辑")
            selection_reasons.append("基础理由包含独立冷门/赔率错配逻辑。")
            risk_notes.append("存在逆向或高波动叙事，临场应复核盘口是否继续支持。")

        if scores["penalty"] >= 10:
            risk_notes.append("该场基础风险不低，不建议作为唯一核心胆。")

        if not risk_notes:
            risk_notes.append("暂无明显附加风险，仍需注意临场盘口异动。")

        return {
            "tags": tags,
            "selection_reasons": selection_reasons[:3],
            "risk_notes": risk_notes[:2],
        }

    def _build_parlay_candidates(self, summary_data):
        candidates = []
        for match in summary_data:
            scores, primary_play, available_plays = self._score_parlay_candidate(match)
            confidence = self._parse_confidence_score(match.get("置信度") or match.get("胜平负置信度"))
            goals_ref = match.get("AI预测进球数") or match.get("进球数参考") or "无"
            annotations = self._build_candidate_annotations(
                confidence=confidence,
                reason=str(match.get("基础理由", "无") or "无"),
                primary_play=primary_play,
                scores=scores,
            )
            tier = "banned"
            if primary_play and confidence >= 70 and scores["stable"] >= 28 and primary_play["options_count"] == 1 and primary_play["max_odds"] <= 2.30:
                tier = "stable"
            elif primary_play and confidence >= 64 and scores["value"] >= 20:
                tier = "value"
            elif primary_play and confidence >= 60 and scores["aggressive"] >= 16:
                tier = "aggressive"

            candidates.append({
                "match_id": match.get("编号", ""),
                "league": match.get("赛事", ""),
                "home_team": match.get("主队", ""),
                "away_team": match.get("客队", ""),
                "match_time": match.get("开赛时间", ""),
                "confidence": confidence,
                "reason": str(match.get("基础理由", "无") or "无"),
                "goals_ref": goals_ref if goals_ref != "无" else "无",
                "score_ref": match.get("比分参考", "无"),
                "raw_match": match,
                "scores": scores,
                "primary_play": primary_play,
                "available_plays": available_plays,
                "tier": tier,
                "tags": annotations["tags"],
                "selection_reasons": annotations["selection_reasons"],
                "risk_notes": annotations["risk_notes"],
            })

        candidates.sort(
            key=lambda item: (
                item["scores"]["stable"],
                item["scores"]["value"],
                item["confidence"],
            ),
            reverse=True,
        )
        return candidates

    def _bucketize_parlay_candidates(self, candidates):
        stable_pool = [item for item in candidates if item["tier"] == "stable"]
        value_pool = [item for item in candidates if item["tier"] in {"stable", "value"}]
        aggressive_pool = [item for item in candidates if item["tier"] in {"value", "aggressive"}]
        fallback_pool = [item for item in candidates if item["tier"] != "banned"]

        stable_pool.sort(key=lambda item: (item["scores"]["stable"], item["confidence"]), reverse=True)
        value_pool.sort(key=lambda item: (item["scores"]["value"], item["scores"]["stable"]), reverse=True)
        aggressive_pool.sort(key=lambda item: (item["scores"]["aggressive"], item["scores"]["value"]), reverse=True)
        fallback_pool.sort(key=lambda item: (item["scores"]["stable"], item["confidence"]), reverse=True)

        return {
            "stable": stable_pool,
            "value": value_pool,
            "aggressive": aggressive_pool,
            "fallback": fallback_pool,
        }

    @staticmethod
    def _rank_candidate_for_plan(candidate, plan_code):
        play = candidate.get("primary_play") or {}
        max_odds = play.get("max_odds", 0.0)
        options_count = play.get("options_count", 1)
        penalty = candidate["scores"].get("penalty", 0)
        estimated_flag = 1 if play.get("estimated") else 0
        cold_flag = 1 if "冷门逻辑" in candidate.get("tags", []) else 0

        if plan_code == "A":
            return (
                candidate["scores"]["stable"],
                -penalty,
                candidate["confidence"],
                -options_count,
                -estimated_flag,
                -abs(max_odds - 1.80),
            )
        if plan_code == "B":
            return (
                candidate["scores"]["value"],
                candidate["scores"]["stable"],
                -penalty,
                -estimated_flag,
                -abs(max_odds - 2.25),
                cold_flag,
            )
        return (
            candidate["scores"]["aggressive"],
            max_odds,
            cold_flag,
            candidate["scores"]["value"],
            -penalty,
            -estimated_flag,
        )

    def _sort_pool_for_plan(self, pool, plan_code):
        return sorted(pool, key=lambda candidate: self._rank_candidate_for_plan(candidate, plan_code), reverse=True)

    @staticmethod
    def _get_plan_target_config(plan_code):
        if plan_code == "A":
            return {
                "target_min": 2.5,
                "target_max": 5.0,
                "preferred_center": 3.6,
            }
        if plan_code == "B":
            return {
                "target_min": 5.0,
                "target_max": 8.0,
                "preferred_center": 6.2,
            }
        return {
            "target_min": 5.0,
            "target_max": None,
            "preferred_center": 8.5,
        }

    @staticmethod
    def _choose_plan_alternative(pool, selected_ids, usage_counter):
        for candidate in pool:
            match_id = candidate["match_id"]
            if match_id in selected_ids:
                continue
            if usage_counter.get(match_id, 0) < 2:
                return candidate
        return None

    @staticmethod
    def _summarize_plan_logic(matches, plan_code):
        if len(matches) < 2:
            return "有效候选不足，当前方案仅供参考。"

        first_tags = set(matches[0].get("tags", []))
        second_tags = set(matches[1].get("tags", []))

        if plan_code == "A":
            return f"以 {matches[0]['match_id']} 与 {matches[1]['match_id']} 组成双稳胆结构，优先保证命中稳定性。"
        if plan_code == "B":
            return f"以 {matches[0]['match_id']} 充当稳胆锚点，搭配 {matches[1]['match_id']} 的价值赔率做中倍增强。"
        if "高倍潜力" in second_tags or "冷门逻辑" in second_tags:
            return f"用 {matches[0]['match_id']} 稳住底盘，再借助 {matches[1]['match_id']} 的高倍逻辑冲击利润。"
        return f"用 {matches[0]['match_id']} 稳住底盘，再由 {matches[1]['match_id']} 提供利润弹性。"

    def _evaluate_candidate_pair(self, first_candidate, second_candidate, plan_code):
        target = self._get_plan_target_config(plan_code)
        best = None

        for play_one, play_two in itertools.product(
            first_candidate.get("available_plays", []) or [first_candidate.get("primary_play")],
            second_candidate.get("available_plays", []) or [second_candidate.get("primary_play")],
        ):
            if not play_one or not play_two:
                continue
            candidate_one = dict(first_candidate)
            candidate_two = dict(second_candidate)
            candidate_one["primary_play"] = play_one
            candidate_two["primary_play"] = play_two

            plan = {
                "plan_code": plan_code,
                "plan_name": "tmp",
                "matches": [candidate_one, candidate_two],
            }
            payout = self._calc_plan_payout(plan)
            net_min = payout["net_min"]
            net_max = payout["net_max"]
            center = (net_min + net_max) / 2
            target_min = target["target_min"]
            target_max = target["target_max"]
            preferred_center = target["preferred_center"]

            hits_lower = net_max >= target_min
            hits_upper = True if target_max is None else net_min <= target_max
            in_band = hits_lower and hits_upper

            gap_penalty = 0.0
            if net_max < target_min:
                gap_penalty += (target_min - net_max) * 10
            if target_max is not None and net_min > target_max:
                gap_penalty += (net_min - target_max) * 8
            gap_penalty += abs(center - preferred_center)

            estimated_penalty = 1 if play_one.get("estimated") else 0
            estimated_penalty += 1 if play_two.get("estimated") else 0
            duplicate_penalty = 50 if first_candidate["match_id"] == second_candidate["match_id"] else 0

            score = (
                200 if in_band else 0,
                -gap_penalty,
                first_candidate["scores"]["stable"] + second_candidate["scores"]["stable"],
                first_candidate["scores"]["value"] + second_candidate["scores"]["value"],
                first_candidate["scores"]["aggressive"] + second_candidate["scores"]["aggressive"],
                -(estimated_penalty + duplicate_penalty),
            )
            item = {
                "score": score,
                "payout": payout,
                "in_band": in_band,
                "matches": [candidate_one, candidate_two],
            }
            if best is None or item["score"] > best["score"]:
                best = item
        if best is None:
            return None, None, False, None
        return best["score"], best["payout"], best["in_band"], best["matches"]

    def _pick_best_pair_for_plan(self, first_pool, second_pool, usage_counter, plan_code):
        ranked_first_pool = self._sort_pool_for_plan(first_pool, "A" if plan_code in {"A", "B", "C"} else plan_code)
        ranked_second_pool = self._sort_pool_for_plan(second_pool, plan_code)

        first_candidates = ranked_first_pool[:6]
        second_candidates = ranked_second_pool[:8]
        best = None

        for first_candidate, second_candidate in itertools.product(first_candidates, second_candidates):
            if first_candidate["match_id"] == second_candidate["match_id"]:
                continue
            if usage_counter.get(first_candidate["match_id"], 0) >= 2:
                continue
            if usage_counter.get(second_candidate["match_id"], 0) >= 2:
                continue

            score, payout, in_band, selected_matches = self._evaluate_candidate_pair(first_candidate, second_candidate, plan_code)
            if not selected_matches:
                continue
            item = {
                "matches": selected_matches,
                "payout": payout,
                "score": score,
                "in_band": in_band,
            }
            if best is None or item["score"] > best["score"]:
                best = item
        return best

    def _build_plan_target_status(self, payout, plan_code):
        target = self._get_plan_target_config(plan_code)
        target_min = target["target_min"]
        target_max = target["target_max"]
        net_min = payout["net_min"]
        net_max = payout["net_max"]

        if target_max is None:
            if net_max >= target_min:
                return f"已达到目标带（目标：{target_min:.1f}+倍）"
            return f"未达到目标带（目标：{target_min:.1f}+倍）"

        if net_max >= target_min and net_min <= target_max:
            return f"已进入目标带（目标：{target_min:.1f}~{target_max:.1f}倍）"
        return f"偏离目标带（目标：{target_min:.1f}~{target_max:.1f}倍）"

    @staticmethod
    def _select_candidate_from_pool(pool, selected_ids, usage_counter, preferred_max_usage=1):
        for candidate in pool:
            match_id = candidate["match_id"]
            if match_id in selected_ids:
                continue
            if usage_counter.get(match_id, 0) <= preferred_max_usage:
                return candidate

        for candidate in pool:
            match_id = candidate["match_id"]
            if match_id not in selected_ids and usage_counter.get(match_id, 0) < 2:
                return candidate
        return None

    def _compose_three_parlay_plans(self, candidates):
        buckets = self._bucketize_parlay_candidates(candidates)
        usage_counter = {}

        def mark_used(candidate):
            if candidate:
                usage_counter[candidate["match_id"]] = usage_counter.get(candidate["match_id"], 0) + 1

        def build_plan(plan_code, plan_name, role_desc, first_pool, second_pool):
            ranked_second_pool = self._sort_pool_for_plan(second_pool, plan_code)
            ranked_fallback_pool = self._sort_pool_for_plan(buckets["fallback"], plan_code)
            pair_choice = self._pick_best_pair_for_plan(first_pool, second_pool, usage_counter, plan_code)
            if pair_choice is None:
                pair_choice = self._pick_best_pair_for_plan(first_pool, buckets["fallback"], usage_counter, plan_code)
            if pair_choice is None:
                pair_choice = self._pick_best_pair_for_plan(buckets["fallback"], buckets["fallback"], usage_counter, plan_code)

            matches = pair_choice["matches"] if pair_choice else []
            selected_ids = {match["match_id"] for match in matches}
            for match in matches:
                mark_used(match)

            payout = pair_choice["payout"] if pair_choice else self._calc_plan_payout({"matches": matches})
            alternative = self._choose_plan_alternative(
                ranked_second_pool or ranked_fallback_pool, selected_ids, usage_counter
            ) or self._choose_plan_alternative(ranked_fallback_pool, selected_ids, usage_counter)

            return {
                "plan_code": plan_code,
                "plan_name": plan_name,
                "role_desc": role_desc,
                "logic_summary": self._summarize_plan_logic(matches[:2], plan_code),
                "matches": matches[:2],
                "alternative": alternative,
                "target_status": self._build_plan_target_status(payout, plan_code),
            }

        return [
            build_plan(
                "A",
                "主推稳健单",
                "稳健盈利优先，只选稳定度最高的两场。",
                buckets["stable"] or buckets["fallback"],
                buckets["stable"] or buckets["value"] or buckets["fallback"],
            ),
            build_plan(
                "B",
                "平衡增益单",
                "以一场稳胆搭配一场价值场，兼顾命中率与中倍回报。",
                buckets["stable"] or buckets["value"] or buckets["fallback"],
                buckets["value"] or buckets["fallback"],
            ),
            build_plan(
                "C",
                "利润冲击单",
                "保留一个稳胆锚点，再加入具备独立爆点逻辑的博胆。",
                buckets["stable"] or buckets["value"] or buckets["fallback"],
                buckets["aggressive"] or buckets["value"] or buckets["fallback"],
            ),
        ]

    @staticmethod
    def _format_match_selection(match):
        play = match.get("primary_play") or {}
        return f"{play.get('label', '玩法')} {play.get('selection', '无')}"

    @staticmethod
    def _calc_plan_payout(plan):
        min_product = 1.0
        max_product = 1.0
        notes_count = 1
        min_factors = []
        max_factors = []
        notes_factors = []
        odds_lines = []
        for match in plan["matches"]:
            play = match.get("primary_play") or {}
            min_odds = play.get("min_odds", 1.0)
            max_odds = play.get("max_odds", 1.0)
            notes = max(1, play.get("options_count", 1))
            min_product *= min_odds
            max_product *= max_odds
            notes_count *= notes
            min_factors.append(f"{min_odds:.2f}")
            max_factors.append(f"{max_odds:.2f}")
            notes_factors.append(str(notes))
            odds_values = []
            for odds in play.get("odds", []):
                odds_text = f"{odds:.2f}"
                if play.get("estimated"):
                    odds_text += " (估算SP)"
                odds_values.append(odds_text)
            odds_lines.append(
                {
                    "match_id": match["match_id"],
                    "selection": play.get("selection", "无"),
                    "odds_text": " / ".join(odds_values),
                    "notes": notes,
                }
            )
        net_min = min_product / notes_count if notes_count else 0.0
        net_max = max_product / notes_count if notes_count else 0.0
        return {
            "min_product": min_product,
            "max_product": max_product,
            "notes_count": notes_count,
            "min_factors": min_factors,
            "max_factors": max_factors,
            "notes_factors": notes_factors,
            "odds_lines": odds_lines,
            "net_min": net_min,
            "net_max": net_max,
        }

    def _render_parlay_markdown(self, plans):
        lines = [
            "## 今日三套实战串子单",
            "",
            "> 生成策略：稳健盈利优先，再平衡中倍与高倍收益；同一场比赛在三套方案中最多出现 2 次。",
            "",
        ]

        for plan in plans:
            payout = self._calc_plan_payout(plan)
            lines.append(f"### 方案{plan['plan_code']}：{plan['plan_name']} (预期净回报：{payout['net_min']:.2f} ~ {payout['net_max']:.2f}倍)")
            lines.append(f"> 🎯 **赔率目标**：{plan.get('target_status', '')}")
            for match in plan["matches"]:
                lines.append(
                    f"* **[{match['match_id']}]** {match['home_team']} VS {match['away_team']} | **推荐：{self._format_match_selection(match)}**"
                )
                lines.append(
                    f"  - 置信度：{match['confidence']} | 标签：{' / '.join(match.get('tags', []))} | 进球数参考：{match['goals_ref']}"
                )
                lines.append(f"  - 入选理由：{'；'.join(match.get('selection_reasons', []))}")
                lines.append(f"  - 风险提示：{'；'.join(match.get('risk_notes', []))}")
            lines.append(f"> 💡 **核心组合逻辑**：{plan['role_desc']}")
            lines.append(f"> 🧭 **组选说明**：{plan.get('logic_summary', '')}")
            if len(plan["matches"]) >= 2 and payout["odds_lines"]:
                lines.append("> 🧮 **赔率推演**：")
                for odds_line in payout["odds_lines"]:
                    lines.append(
                        f"> - {odds_line['match_id']} ({odds_line['selection']}): 赔率 {odds_line['odds_text']}"
                    )
                lines.append(f"> - 注数计算: {' × '.join(payout['notes_factors'])} = {payout['notes_count']} 注")
                lines.append(f"> - 理论最低赔率: {' × '.join(payout['min_factors'])} = {payout['min_product']:.2f}")
                lines.append(f"> - 理论最高赔率: {' × '.join(payout['max_factors'])} = {payout['max_product']:.2f}")
                lines.append(f"> - 真实净回报：最低 {payout['net_min']:.2f} 倍 ~ 最高 {payout['net_max']:.2f} 倍")
            else:
                lines.append("> 🧮 **赔率推演**：当前未凑齐满足约束的两场组合，请结合备选替换场人工调整。")
            alternative = plan.get("alternative")
            if alternative:
                lines.append(
                    f"> 🔁 **备选替换场**：[{alternative['match_id']}] {alternative['home_team']} VS {alternative['away_team']} | {self._format_match_selection(alternative)}"
                )
                lines.append(
                    f"> - 替换理由：{'；'.join(alternative.get('selection_reasons', []))}"
                )
            lines.append("")
        return "\n".join(lines).strip()

    def _build_parlay_payload(self, plans):
        payload = []
        for plan in plans:
            payout = self._calc_plan_payout(plan)
            payload.append({
                "plan_code": plan["plan_code"],
                "plan_name": plan["plan_name"],
                "target_status": plan.get("target_status", ""),
                "role_desc": plan.get("role_desc", ""),
                "logic_summary": plan.get("logic_summary", ""),
                "payout": payout,
                "matches": [
                    {
                        "match_id": match["match_id"],
                        "home_team": match["home_team"],
                        "away_team": match["away_team"],
                        "confidence": match["confidence"],
                        "tags": match.get("tags", []),
                        "goals_ref": match.get("goals_ref", "无"),
                        "selection_reasons": match.get("selection_reasons", []),
                        "risk_notes": match.get("risk_notes", []),
                        "selection_text": self._format_match_selection(match),
                    }
                    for match in plan["matches"]
                ],
                "alternative": (
                    {
                        "match_id": plan["alternative"]["match_id"],
                        "home_team": plan["alternative"]["home_team"],
                        "away_team": plan["alternative"]["away_team"],
                        "selection_text": self._format_match_selection(plan["alternative"]),
                        "selection_reasons": plan["alternative"].get("selection_reasons", []),
                    }
                    if plan.get("alternative") else None
                ),
            })
        return payload

    def generate_parlays_payload(self, summary_data):
        try:
            candidates = self._build_parlay_candidates(summary_data)
            valid_candidates = [candidate for candidate in candidates if candidate["tier"] != "banned"]
            if len(valid_candidates) < 2:
                message = "❌ 可用于串关的有效场次不足 2 场，请先补充完整预测或等待更多比赛数据。"
                return {"markdown": message, "plans": []}

            plans = self._compose_three_parlay_plans(candidates)
            return {
                "markdown": self._render_parlay_markdown(plans),
                "plans": self._build_parlay_payload(plans),
            }
        except Exception as e:
            logger.error(f"调用 LLM 生成串关方案失败: {e}")
            message = f"❌ 生成串关方案失败，请检查 API 配置或网络连接。错误信息: {e}"
            return {"markdown": message, "plans": []}

    def generate_parlays(self, summary_data):
        """
        基于当日预测结果，生成三套固定模板的实战串关方案
        """
        return self.generate_parlays_payload(summary_data)["markdown"]

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
