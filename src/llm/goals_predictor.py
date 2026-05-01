import json
import logging
import os
import sys

# 确保能找到 src 目录
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.llm.predictor import LLMPredictor

logger = logging.getLogger(__name__)

class GoalsPredictor(LLMPredictor):
    def __init__(self):
        super().__init__()
        # 覆写基础系统提示，专注于进球数预测
        self.system_prompt = """你是一个世界顶级的足球数据分析师与博彩操盘手，专门研究"进球数预测"和"大小球盘口"。
你精通基于历史大数据统计结合联赛基本面的进球数概率推演。

## Analysis Workflow (进球数专属分析工作流)
请严格按照以下步骤进行思考和分析，并在最终回复中呈现你的思考过程：

1. **基于盘口的博弈论思维**：
   - 机构开出的进球数盘口是核心锚点。你需要判断机构是“看好并防范”还是“故意诱导”。
   - **【深盘诱大预警】**：当进球数盘口达到或超过 `3.5`，且包含五大联赛顶级豪门（如曼城、拜仁、巴萨、巴黎等）时，这极大概率是机构的**诱大陷阱**。豪门在密集赛程下极易采用“经济适用”踢法。除非客队防线有极其严重的伤病，否则必须将预测核心放在 **1-3球**（小球方向），严禁盲目给出 4-5 球的预测。
   - **【浅盘惨案预警】**：当进球数盘口仅为 `2.5` 或 `2.5/3`，但对阵双方存在以下情况时：（1）强队主场迎战弱旅且近期进攻极佳；（2）保级/争冠关键战中一方防线脆弱。此时不要被保守的盘口迷惑，极易打出单方面屠杀或对攻大战。请大胆将 **4-5球** 纳入核心预测选项。

2. **防守联赛DNA与大球联赛冷门**：
   - **【防守联赛DNA】**：西甲、法乙、葡超等天生防守型联赛，严禁盲目预测3球以上，即使盘口开到2.5也应优先防范1-2球。
   - **【大球联赛冷门陷阱】**：荷甲、美职联等自带“大球属性”的联赛，若开出3/3.5深盘但基本面不支持（如主力伤停或近期进攻哑火），往往是机构利用公众固有思维的“高开低走诱大”陷阱，极易打出0-2球。

3. **结合基本面的双向验证**：
   - 重点关注我为你计算的【场均进球】和【场均失球】数据，将其作为判断进攻火力的直接锚点。
   - **【伤停减档预警】**：当伤病名单中包含明确的主力前锋或中前场核心球员，或首发阵容残缺时，球队的进攻火力将大打折扣。此时你的进球数预期必须**强制下调1档**（即预期进球数减1）。
   - 特别注意杯赛或保级关键战中的战意，可能会导致极端沉闷或极端奔放的比赛。

4. **提取历史统计基准概率（绝对服从）**：
   - 仔细查阅我提供给你的【进球数概率分布历史统计】数据。
   - **【统计分布约束】**：请严格参考提供的历史统计。如果历史统计中该盘口下“小球（0-2球）”的概率超过 60%，你的预测**必须**包含 1球 或 2球，绝不允许与历史大概率背道而驰。
   - 当基本面结论与统计学最高概率一致时，可以大胆给出单点预测；如果出现分歧，应优先尊重统计概率，辅以基本面微调。

5. **最终进球数收敛**：
   - 将最有可能的进球数收敛到 1-2 个核心数字。

## Output Format (输出格式要求)
请以清晰、专业的排版输出你的分析报告：

**【核心逻辑推演】**
[此处写下你的分析过程，控制在150字以内。]

**【统计数据洞察】**
- 所属联赛与特征组：[直接填入系统提示的联赛和特征组，如 英超 | C组：主流均衡型]
- 组内进球概率分布：[直接填入系统提示的组内分布，如 3球(2场)，2球(1场)]
- 全局进球概率分布：[直接填入系统提示的全局分布，如 3球(5场)，2球(4场)]

**【进球数预测】**
[必须明确提供 1-2 个最可能的总进球数，例如：2, 3球。最多给3个数字，强烈建议只给2个核心进球数]
"""

    def _format_match_data(self, match):
        """将比赛数据格式化为 Prompt 可读的文本"""
        info = super()._format_match_data(match)
        
        # 进球数后验分析补充数据 (从 Excel 传入)
        info += f"\n- **【机构进球数深度数据】**：\n"
        info += f"  - 进球盘口: {match.get('goals_pan', '暂无')}\n"
        info += f"  - 预测差异百分比: {match.get('goals_diff_percent', '暂无')}\n"
        info += f"  - 机构倾向: {match.get('goals_trend', '暂无')}\n"
        
        return info

    def _determine_cluster_with_llm(self, home_team, away_team):
        """利用大模型根据对阵双方的所属联赛判定特征组"""
        prompt = f"""
        你是一个足球数据分类专家。
        请根据主队“{home_team}”和客队“{away_team}”所在的国内联赛，判断它们在进球数预测中所属的特征组。
        
        特征组定义：
        A组（开放大开大合型）：澳超, 挪超, 荷甲, 瑞超, 美职足, 沙特职业联赛, 芬兰超级联赛
        B组（严密防守型）：意甲, 西乙, 法乙, 阿甲, 葡超, 英冠, 解放者杯, 南美杯
        C组（主流均衡型）：英超, 德甲, 西甲, 法甲, 德乙
        D组（日韩孤立型）：日职, 韩职, 韩K
        
        如果两支球队同属一个特征组，请直接返回该特征组。
        如果两支球队属于不同特征组，或者无法准确找到对应特征组，请根据它们综合的进球属性（偏大球还是偏小球）折中给出一个最合适的组别。
        如果实在无法判断，请返回“C组：主流均衡型”。
        
        请只输出组别的名称，例如：“A组：开放大开大合型”、“B组：严密防守型”、“C组：主流均衡型”或“D组：日韩孤立型”，不要输出任何多余的解释。
        """
        try:
            logger.info(f"正在通过大模型判定 {home_team} VS {away_team} 的所属特征组...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个精准的分类助手，只输出规定的分类名称。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=20
            )
            res = response.choices[0].message.content.strip()
            if "A组" in res: return "A组：开放大开大合型"
            elif "B组" in res: return "B组：严密防守型"
            elif "C组" in res: return "C组：主流均衡型"
            elif "D组" in res: return "D组：日韩孤立型"
            else: return "C组：主流均衡型"
        except Exception as e:
            logger.error(f"大模型判定特征组失败: {e}")
            return "C组：主流均衡型"

    def get_statistical_prediction(self, match_data):
        import sqlite3
        import pandas as pd
        import os
        
        # 1. determine cluster
        league = str(match_data.get('league', ''))
        home_team = str(match_data.get('home_team', ''))
        away_team = str(match_data.get('away_team', ''))
        
        special_leagues = ['欧冠', '欧联', '欧罗巴', '欧协联', '欧国联', '世预赛', '欧洲杯', '亚洲杯', '美洲杯', '俱乐部杯', '亚冠', '亚洲']
        is_special = any(sl in league for sl in special_leagues)
        
        if is_special:
            cluster = self._determine_cluster_with_llm(home_team, away_team)
        else:
            group_a = ['澳超', '挪超', '荷甲', '荷乙', '瑞超', '美职足', '沙特职业联赛', '芬兰超级联赛']
            group_b = ['意甲', '西乙', '法乙', '阿甲', '葡超', '英冠', '解放者杯', '南美杯']
            group_c = ['英超', '德甲', '西甲', '法甲', '德乙']
            group_d = ['日职', '韩职', '韩K']
            
            cluster = 'E组：其他未分类联赛'
            for g in group_a:
                if g in league: cluster = 'A组：开放大开大合型'
            for g in group_b:
                if g in league: cluster = 'B组：严密防守型'
            for g in group_c:
                if g in league: cluster = 'C组：主流均衡型'
            for g in group_d:
                if g in league: cluster = 'D组：日韩孤立型'
            
        pan = str(match_data.get('goals_pan', '')).strip()
        
        try:
            diff_raw = str(match_data.get('goals_diff_percent', '')).strip()
            if diff_raw.endswith('%'):
                diff = float(diff_raw.strip('%')) / 100.0
            else:
                diff = float(diff_raw)
        except:
            diff = 0.0
            
        trend = str(match_data.get('goals_trend', '')).strip()
        
        if not pan or not trend or pan == 'nan' or trend == 'nan':
            return None, cluster, "无匹配", "无匹配"
            
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'football.db')
        if not os.path.exists(db_path):
            return None, cluster, "无匹配", "无匹配"
            
        conn = sqlite3.connect(db_path)
        try:
            history_df = pd.read_sql("SELECT pan, diff, trend, actual_goals, cluster FROM goal_analysis_history", conn)
        except:
            return None, cluster, "无匹配", "无匹配"
        finally:
            conn.close()
            
        if history_df.empty:
            return None, cluster, "无匹配", "无匹配"
            
        def find_top_goals(target_diff):
            tol = 0.01
            mask = (history_df['cluster'] == cluster) & \
                   (history_df['pan'] == pan) & \
                   (history_df['trend'] == trend) & \
                   (abs(history_df['diff'] - target_diff) < tol)
            matches = history_df[mask]
            if not matches.empty:
                counts = matches['actual_goals'].value_counts()
                top_2 = counts.head(2).index.tolist()
                
                # 记录场次分布
                dist = []
                for g, c in counts.items():
                    dist.append(f"{int(g)}球({c}场)")
                dist_str = "，".join(dist)
                
                return top_2, dist_str
            return None, None
            
        def find_all_cluster_goals(target_diff):
            tol = 0.01
            mask = (history_df['pan'] == pan) & \
                   (history_df['trend'] == trend) & \
                   (abs(history_df['diff'] - target_diff) < tol)
            matches = history_df[mask]
            if not matches.empty:
                counts = matches['actual_goals'].value_counts()
                dist = []
                for g, c in counts.items():
                    dist.append(f"{int(g)}球({c}场)")
                dist_str = "，".join(dist)
                return dist_str
            return "无匹配"
            
        # exact match
        top_goals, dist_str = find_top_goals(diff)
        all_cluster_dist_str = find_all_cluster_goals(diff)
        
        # downgrade diff if not found
        if not top_goals:
            diffs_to_try = [1.0, 0.75, 0.50, 0.25, 0.0]
            diffs_to_try.sort(key=lambda x: abs(x - diff))
            for d in diffs_to_try:
                if abs(d - diff) < 0.01: continue
                top_goals, dist_str = find_top_goals(d)
                all_cluster_dist_str = find_all_cluster_goals(d)
                if top_goals:
                    break
                    
        if top_goals:
            goals_str = ", ".join([str(int(g)) for g in sorted(top_goals)]) + "球"
            return goals_str, cluster, dist_str, all_cluster_dist_str
            
        return None, cluster, "无匹配", "无匹配"

    def predict(self, match_data, total_matches_count=1):
        """执行预测"""
        # 如果没有进球数盘口数据，则不进行预测
        if not match_data.get('goals_pan') and not match_data.get('goals_diff_percent') and not match_data.get('goals_trend'):
            return "【无进球数机构数据，放弃预测】", "final"
            
        # 1. 获取纯统计学匹配预测
        stat_goals, cluster, dist_str, all_cluster_dist_str = self.get_statistical_prediction(match_data)
        
        # 2. 依然调用 LLM 进行基本面等综合分析
        prompt = self._format_match_data(match_data)
        
        league = match_data.get('league', '未知联赛')
        
        if stat_goals:
            prompt += f"\n- **【系统提示】**：\n"
            prompt += f"  - 所属联赛：{league} | 匹配特征组：{cluster}\n"
            prompt += f"  - 在该特征组内匹配到的历史赛果分布为：{dist_str}。最高概率进球数为：**{stat_goals}**。\n"
            prompt += f"  - 不区分特征组，仅看盘口/差异/倾向匹配到的全局赛果分布为：{all_cluster_dist_str}。\n"
            prompt += f"  请你在此基础上结合基本面深度推演，给出基本面视角的最终预测。"
        else:
            prompt += f"\n- **【系统提示】**：\n"
            prompt += f"  - 所属联赛：{league} | 匹配特征组：{cluster}\n"
            prompt += f"  - 系统未能在历史数据库中找到完全匹配的盘口条件，请你完全基于自身逻辑和基本面进行深度推演。"
            
        try:
            logger.info(f"正在调用大模型 ({self.model}) 进行进球数专项预测: {match_data.get('match_num')}")
            
            # 读取目标进球数统计报告作为背景知识
            bg_knowledge = ""
            report_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "goal_distribution_analysis.md")
            if os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    bg_knowledge = f.read()
                    
            if bg_knowledge:
                prompt += f"\n\n**【进球数概率分布历史统计（供参考）】**\n{bg_knowledge[:2000]}... (仅截取部分)"
                
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"请分析以下比赛进球数数据并给出预测：\n\n{prompt}"}
                ],
                temperature=0.7,
                max_tokens=1500
            )
            result = response.choices[0].message.content
            
            # 如果是字典形式返回，我们需要在调用端处理，但为了兼容现有的接口，我们把统计预测也塞进返回值里
            import json
            final_res = json.dumps({
                "statistical_goals": stat_goals,
                "fundamental_report": result
            }, ensure_ascii=False)
            
            return final_res, "final"
        except Exception as e:
            logger.error(f"进球数预测失败 {match_data.get('match_num')}: {e}")
            return f"预测失败: {str(e)}", "final"
