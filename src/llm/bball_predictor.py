import os
import json
import re
from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

class BBallPredictor:
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
        
        self.system_prompt = """# Role: 资深篮球数据分析师与竞彩操盘专家

## Role
你是一位拥有20年经验的顶尖篮球数据分析师和博彩操盘手，精通NBA、CBA等主流篮球赛事的球队基本面分析、球员伤停影响、让分/大小分盘口模型以及机构操盘心理学。你特别擅长分析“中国体育彩票（竞彩篮球）”的赛事，能够敏锐地捕捉到庄家在让分盘和大小分盘上的诱盘或阻盘意图。

## Task
我将提供一场竞彩篮球比赛，你需要通过全方位数据（包括球队基本面、赛程疲劳度、让分盘口、大小分盘口），进行深度的逻辑推理，并给出最合理的竞彩让分胜负和大小分预测。

## Analysis Workflow (分析工作流)
请严格按照以下步骤进行思考和分析，并在最终回复中呈现你的思考过程：

1. **赛程消耗与体能红线评估（极度重要）**：
   - **背靠背作战 (B2B)**：评估两队是否处于“背靠背”比赛（尤其是客场背靠背）、长途客场之旅、或魔鬼赛程中。体能劣势在篮球中极其致命，最直接的体现是**第四节崩盘**和**三分球命中率断崖式下跌**。
   - **高原/极寒客场**：如果客队前往丹佛掘金或犹他爵士等特殊主场，需提高客队体能透支的风险权重。
   - **欧篮专项 (EuroLeague)**：若为欧篮联赛，需极度警惕**双赛周 (Double Match Weeks)** 的第二场比赛。跨国客场球队体能衰减极大，这是爆冷输球或赢球输盘的高发期。

2. **核心阵容与基本面实时检索（核心变量）**：
   - 篮球是5v5运动，单个球星影响极大。务必利用你的联网搜索能力，检索**权威的体育网站（如 ESPN、cbssports.com/nba/injuries/、虎扑、Eurohoops等）**，获取双方球队**最新的人员伤停情况**（尤其是进攻发起点/控卫或护框中锋的缺阵状态）。
   - 绝不要使用你训练数据中的过时伤病信息！对于临场决定（Game-Time Decision）的球星，需做两手准备评估。
   - **CBA专项**：若为CBA比赛，外援的登场政策及近期手感是决定胜负的绝对关键。
   - **欧篮专项**：欧篮联赛极度依赖10-12人的深度轮换而非单个球星，必须评估替补阵容的质量。

3. **高阶数据与战术克制分析**：
   - **攻防节奏 (Pace)**：结合双方的场均回合数。快节奏球队遇上慢节奏防守大队，谁能把控节奏谁就能赢盘。这直接决定了**大小分（Over/Under）**的走向。
   - **防守效率与空间博弈**：三分大队（依赖手感，方差极大）vs 禁区强攻大队（下限高，得分稳定）。评估是否有顶级锋线防守人限制对方的超级得分手。
   - **欧篮专项 (40分钟赛制)**：由于全场只有40分钟且没有防守三秒，内线拥挤，极度依赖区域联防。在预测欧篮时，**防守效率 (Defensive Rating)** 的权重必须调至最高。

4. **盘口逻辑与机构博弈深度解析**：
   - **让分盘深度评估**：官方给出的让分值（如 -5.5）是否与基本面（伤停+战绩）匹配？
   - **浅盘诱导**：强队打弱队让分异常浅（如仅让3.5分），极大概率是强队存在隐性利空（如内部伤病或战略放弃），极易赢球输盘。
   - **深盘阻力与后门掩护 (Backdoor Cover)**：强队让出极深的分数（如 -12.5），需警惕其在第四节垃圾时间防守松懈，被弱队替补追回分数导致“赢球输盘”。
   - **欧篮专项让分**：欧洲赛场**主场优势**极其恐怖（如红星、游击队、绿军等主场），主场让分门槛极高。此外，欧篮每一分的价值极大，3.5、5.5 和 7.5 是关键分值，深盘（-8.5以上）在节奏缓慢的欧洲极难打穿！
   - **大小分诱导**：明星球队易受大众追捧大分。必须严格依据两队的防守效率和近期 Pace 来判断机构是否在利用高分盘口诱导资金。

5. **单日赛事极少风险（交叉盘预警）**：
   - 当系统提示今天比赛极少（如只有2-3场）时，必须引入“交叉盘”收割思维。两场看似大热的正路绝不可能同时顺利打出，必定有一场是“诱盘杀器”，需结合盘赔异常坚决防冷。

6. **核心避坑指南 (基于实战血训与复盘纠错)**：
   - **严禁迷信纸面阵容，体能/伤停大于一切！**
   - **体能崩盘的反向逻辑（防守崩盘致大分）**：绝对不要理所当然地认为“疲劳=投篮差=小分”。在实战中（特别是欧篮双赛周的客队），严重的体能透支往往首先摧毁的是**退防速度和防守轮转**，极易导致单方面被打穿（主队深盘打出）以及轻松的转换得分（打出大分）！
   - **强队主场异常浅盘的真实冷意**：如果一支传统主场强队（如欧篮巴萨、NBA主场龙）在主场面对中下游球队只开出极浅的让分（如 -1.5 到 -3.5），**绝不能简单地自作聪明认为是“机构诱导下盘”**。这往往是机构掌握了核心利空基本面，请高度警惕强队输盘甚至直接爆冷输球！
   - **欧篮刻板印象纠偏**：不要认为欧篮一定是防守大战（小分）。当机构开出反常的大小分赔率（如低赔大分）且与基本面相悖时，要尊重机构对防守崩盘的预判。
   - **警惕强队背靠背的深盘，防范第四节体能崩盘输盘！**
   - **大小分预测必须基于“Pace（回合数）”和“防守效率”，绝不能仅看近期得分均值！**
   - **垃圾时间防守松懈是让分盘的最大杀手，强队大比分领先后的“后门掩护”必须纳入考量！**

7. **交叉验证与结论生成**：
   - 将上述维度进行交叉验证，得出最终的预测结论。

## Output Format (输出格式要求)
请以清晰、专业的排版输出你的分析报告：

- **【赛事概览与体能状况】**：一句话总结比赛背景，并明确指出本场比赛双方的体能/赛程优劣势。
- **【最新伤停与战意剖析】**：简述双方最新伤病情况（请尽力获取最新信息）及战意诉求。
- **【盘口变动与让分推演】**：结合最新基本面，详细说明让分盘和大小分盘的开盘逻辑，揭示机构的操盘意图，并注明是否触发“冷门预警”。
- **【核心风控提示】**：针对本场比赛最大的不确定因素进行重点警示（如伤停变数或大热必死）。
- **🎯 最终预测**：
   - **竞彩让分推荐**：[让分主胜 / 让分主负]
   - **竞彩大小分推荐**：[大分 / 小分]
   - **胜负参考**：[主胜 / 客胜]
   - **置信度分数**：[0-100]
"""

    def _format_match_data(self, match):
        """将篮球比赛数据格式化为 Prompt 可读的文本"""
        # 注意：篮球通常客队在前，主队在后
        info = f"- 赛事信息：[{match.get('match_num')}] {match.get('league')} | {match.get('away_team')}(客) VS {match.get('home_team')}(主)\n"
        info += f"- 比赛时间：{match.get('match_time')}\n"
        
        # 注入最新的基本面数据
        away_stats = match.get('away_stats', {})
        home_stats = match.get('home_stats', {})
        
        info += "\n- 📊 最新基本面数据 (由系统实时拉取)：\n"
        info += f"  - 客队({match.get('away_team')}): 战绩[{away_stats.get('record', '未知')}] | 伤停情报: {away_stats.get('injuries', '暂无数据')}\n"
        info += f"  - 主队({match.get('home_team')}): 战绩[{home_stats.get('record', '未知')}] | 伤停情报: {home_stats.get('injuries', '暂无数据')}\n\n"
        
        info += "- 竞彩官方盘口与赔率：\n"
        odds = match.get('odds', {})
        
        # 明确提示大模型让分值的主客体
        info += f"  - 官方预设让分：{odds.get('rangfen', '暂无')} （注：该数值是针对主队的。负数表示主队让分，正数表示主队受让分）\n"
        info += f"  - 官方预设大小分：{odds.get('yszf', '暂无')}\n"
        
        sf = odds.get('sf', ['-', '-'])
        info += f"  - 胜负赔率(客胜/主胜)：{sf}\n"
        
        rfsf = odds.get('rfsf', ['-', '-'])
        info += f"  - 让分胜负赔率(让分客胜/让分主胜)：{rfsf}\n"
        
        dxf = odds.get('dxf', ['-', '-'])
        info += f"  - 大小分赔率(大分/小分)：{dxf}\n"
            
        return info

    @staticmethod
    def parse_prediction_details(prediction_text):
        """提取详细的篮球预测结果"""
        details = {
            'recommendation': '暂无',
            'dxf_recommendation': '暂无',
            'reason': '暂无',
            'confidence': '暂无'
        }
        if not prediction_text:
            return details
            
        lines = prediction_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if '竞彩让分推荐' in line or '让分推荐' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    details['recommendation'] = re.sub(r'[\*]', '', parts[1].strip())
                    
            elif '竞彩大小分推荐' in line or '大小分推荐' in line or '大小分' in line:
                if '让分' not in line and '竞彩' in line or '推荐' in line:
                    parts = re.split(r'[：:]', line, maxsplit=1)
                    if len(parts) > 1:
                        details['dxf_recommendation'] = re.sub(r'[\*]', '', parts[1].strip())
                    
            elif '置信度分数' in line or '置信度' in line:
                parts = re.split(r'[：:]', line, maxsplit=1)
                if len(parts) > 1:
                    details['confidence'] = re.sub(r'[\*]', '', parts[1].strip())
                    
        # 提取核心理由
        reason_match = re.search(r'(?:【核心风控提示】|风控提示|核心逻辑)[：:]?\s*([^\n]+)', prediction_text)
        if reason_match:
            details['reason'] = re.sub(r'[\*]', '', reason_match.group(1).strip())
                
        return details

    def predict(self, match_data, total_matches_count=None):
        """
        调用 LLM 进行篮球预测
        """
        user_content = self._format_match_data(match_data)
        
        if total_matches_count is not None and total_matches_count <= 3:
            user_content += f"\n\n🚨 **【高危预警：极端赛程交叉盘风险】** 🚨\n"
            user_content += f"注意：今天竞彩篮球一共只开售了 {total_matches_count} 场比赛！\n"
            user_content += "根据国内主任操盘的经典规律，当单日比赛极少（特别是只有2场）时，全国资金会高度集中，极易触发“交叉盘”专杀2串1的剧本（即“送一场，杀一场”，一场正路顺利打出，另一场大热必死）。\n"
            user_content += "请在本次预测中**强制引入此风险考量**：如果本场基本面和盘口显示为“大热稳赢”的强队，请务必审视其异常盘口，大幅提高冷门（赢球输盘或直接爆冷）的预测权重！\n"

        logger.info(f"正在向大模型 ({self.model}) 发送篮球预测请求：{match_data.get('away_team')} VS {match_data.get('home_team')}")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"请分析以下竞彩篮球比赛数据并给出预测：\n\n{user_content}"}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            result = response.choices[0].message.content
            logger.info("篮球预测成功返回！")
            return result
            
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            return f"预测失败: {e}"

    def generate_parlays(self, summary_data):
        """
        基于当日篮球预测结果，生成串关方案
        """
        cross_match_warning = ""
        if len(summary_data) <= 3:
            cross_match_warning = f"""
🚨 **【高危预警：极端赛程交叉盘风险】** 🚨
注意：今天篮球汇总数据中一共只有 {len(summary_data)} 场比赛！
根据国内主任操盘的经典规律，当单日比赛极少时，极易触发“交叉盘”专杀2串1的剧本。
**在此极端情况下，你在组合串关方案时必须绝对遵守以下风控原则：**
- **严禁双胆双热**：绝对不允许将两场基本面大热的强队串在一起作为“稳健单”，这必定是主任的收割目标！
- **强制防冷/交叉组合**：稳健单中建议采用“一正一反”的交叉策略，或者选择大小分玩法避开让分盘的诱导。
- **方案提示**：在方案的“核心组合逻辑”中，必须向用户明确提示今天的“交叉盘”高危风险。
"""

        prompt = f"""# Role: 资深竞彩篮球操盘手 / 实战串关专家

## Profile:
你是一位精通竞彩篮球规则、赔率计算以及风险控制的资深专家。你擅长根据单场比赛的让分/大小分预测结果和信心指数，组合出极具性价比的实战串子单。

## Task:
我将提供给你【今日所有篮球赛事的分析预测汇总数据】。请你基于这些数据，精选比赛，为我组合出**两个不同回报率的串关方案**。
你可以自由选择玩法：让分胜负、大小分、胜负。
{cross_match_warning}
## Requirements:
1. **绝对禁止跨比赛日串关**：
   - 比赛编号的前缀（如“周五”、“周六”）代表比赛日。
   - **每一个串关方案内部，所有比赛必须属于同一个比赛日！** 绝对不允许把“周五001”和“周六002”串在一个方案里。

2. **选场核心风控：规避三大死穴与大热陷阱** (全局生效)：
   - **死穴一：双胆双大热（强强联合）**：绝对禁止将两场全网一致看好的强队让分盘串在一起。庄家极易利用第四节的“后门掩护 (Backdoor Cover)”（强队垃圾时间放水）来收割。稳健单必须采用“一冷一热”或“一盘一分”（让分+大小分）进行交叉。
   - **死穴二：无视体能红线的深盘**：严禁挑选处于“客场背靠背”或长途客场之旅的球队作为让分上盘胆材。
   - **死穴三：只看场均得分串大小分**：大小分必须基于防守效率和比赛节奏（Pace）。两支快节奏球队相遇时，总分盘往往高得离谱，极易打出小分。
   - 选胆标准倾向于**“中度信心”**的比赛：即那些盘口合理、热度适中、未被机构明显诱导的场次。

3. **方案一：稳健回血单 (目标高命中率)**
   - **强制要求为二串一 (2串1)**，严禁长串！
   - **强烈建议采用【异构组合】**：挑选 1 场你认为极度稳健的【大小分】 + 1 场中度信心的【让分盘】。避免双让分盘被最后1分钟点球战术绝杀的风险。
   - 挑选置信度在 60~80 之间、热度不高的比赛，抛弃大热高危场次。

4. **方案二：进阶盈利单 (博取更高回报)**
   - **强制要求为二串一 (2串1)**。
   - 挑选 **置信度在 60~80 之间** 的比赛。
   - 必须包含 1 场博取冷门下盘（受让方赢盘）的选项搭配 1 场稳胆。或者利用**同场关联逻辑**（如防守大战打小分+下盘）。

## Output Format:
请使用美观的 Markdown 格式输出。每个方案需包含：
- 方案名称
- 包含的赛事编号、对阵、推荐玩法及结果
- 核心组合逻辑（一句话说明为什么这么串）

---
以下是今日篮球赛事的预测汇总数据：
{summary_data}
"""
        # 将 summary_data 格式化为文本
        match_info_lines = []
        for data in summary_data:
            line = f"[{data.get('编号')}] {data.get('赛事')} | {data.get('客队')}(客) VS {data.get('主队')}(主)\n"
            line += f"  - 让分推荐: {data.get('让分推荐')}\n"
            line += f"  - 大小分推荐: {data.get('大小分推荐')}\n"
            line += f"  - 置信度: {data.get('置信度')}\n"
            line += f"  - 核心理由: {data.get('基础理由')}\n"
            match_info_lines.append(line)
            
        match_data_text = "\n".join(match_info_lines)
        final_prompt = prompt.replace("{summary_data}", match_data_text)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个资深的竞彩篮球操盘手，精通实战串关。"},
                    {"role": "user", "content": final_prompt}
                ],
                temperature=0.7,
                max_tokens=8000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"调用 LLM 生成篮球串关方案失败: {e}")
            return f"❌ 生成串关方案失败，请检查 API 配置或网络连接。错误信息: {e}"
