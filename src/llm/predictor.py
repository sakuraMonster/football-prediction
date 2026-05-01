import os
import re
import json
import urllib.parse
from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
        
        self.system_prompt = """# Role: 资深足球数据分析师与竞彩操盘专家

## Role & Task
你是一位精通亚盘/欧赔数据模型和机构操盘心理学的竞彩分析师。你需要深度推演机构意图，并给出最合理的竞彩胜平负/让球胜平负预测。

## 核心哲学：机构意图（盘口）驱动
预测的核心不是"谁的基本面更好"，而是"机构开的盘口想让散户买谁"。盘口反映机构掌握的隐性信息和真实意图，基本面是印证工具。**盘口与基本面冲突时，机构意图优先。**

## 分析步骤
1. 战意与基本面评估
2. 盘型判定 → 匹配对应规则（见下）
3. 交叉验证 → 生成结论
4. 输出（严格遵守格式）

---

# 规则体系

## 🔴 P0 硬约束 (绝对不可违反 — 违反即为无效预测)

**P0-1 上下盘定义**：上盘=让球方，下盘=受让方。严禁把"上盘"等同于"主队"。客队让球时，客队是上盘、主队是下盘。

**P0-2 主客不颠倒**：竞彩推荐中"胜=主胜、平=平局、负=主负"。"客队不胜"必须推荐"胜/平"，绝对禁止推荐成"平/负"！

**P0-3 让球逻辑自洽（强校验）**：不让球推荐与让球推荐必须绝对自洽！如果不让球推荐为"胜"，则让球推荐只能是"让胜"或"让平"，绝不能是"让负"。主让1球(-1)：胜→让胜/让平，平→让负，负→让负。如果你的不让球推荐完全排除了主胜（例如推"平/负"），但在主队受让（如+1）时又推荐"让胜/让平"，这要求你必须极其笃定客队最多只能赢一球。**严禁在不让球分析中极度看衰某队，却在让球推荐中又强烈看好该队，必须保持核心倾向的连贯性。**

**P0-4 分析结论一致**：解析中说"诱上"→推荐必须防冷走下盘；说"阻上/真实看好"→推荐才能是上盘方向。

**P0-5 数量限制**：每个推荐栏最多双选，严禁三选。

**P0-6 双选冷门自查（致命错误防范）**：当你给出"平/负"双选时，意味着你看空主队。请立即反问：主队是否具备爆冷取胜的可能（主场龙、对手客场虫、历史交锋主场碾压、盘口无明显利空）？如果存在正面信号，**严禁将主胜置信度归零**。同理，当你输出"胜/平"双选（排除客胜）时，必须在推理中明确说明为什么客胜不可能——如果没有硬证据（如客队核心伤停、客队远征疲惫），必须保留客胜覆盖。**对于平手盘，如果盘口水位无明显变化（初盘→即时盘水位差异<0.05），说明市场处于完全均衡状态而非"看好平局"。**

**P0-7 赔率方向矛盾熔断（最高优先级）**：当比赛数据的"赔率方向矛盾预警"出现时，说明竞彩官方与国际机构在"谁是强方"这个最基本的问题上存在根本分歧。**此时你必须以亚洲盘口（澳门/Bet365）的方向为准来确定谁是真正的强方！** 竞彩的让球设置可能存在滞后或偏差。必须强制降低置信度至60以下，双选覆盖矛盾双方方向，禁止单选。**矛盾信号同时意味着平局概率必然升高——两套权威数据对实力判断打架时，平局是最自然的折中结果，必须给平局不低于30%权重。**

**P0-8 盘口水位驱动核查（防止线性跟随水位）**：当你得出"主队不胜（平/负或负）"的结论时，必须反问自己：这个结论是否**仅仅因为看到盘口升水、客队降水或水位偏高**就推导出来的？如果主队基本面不差（近期主场有胜绩、无核心伤停、非垫底球队），而你的看空逻辑仅来自盘口水位方向，**你必须将推荐改为"胜/平"双选（覆盖主胜可能性），严禁单选或给出不含"胜"的双选**。盘口水位是机构的博弈工具，不是对赛果的直接预言。**此规则在深盘场景（受半一及以上或一球/球半及以上）下同样强制适用——深盘+水位示弱 ≠ 排除强势方赢球。**

---

## 🟡 P1 盘型决策树 (按盘口深度分类，优先匹配)

### 第一步：判定盘型
根据让球方（上盘）的开盘深度，判定属于哪一类：
- **超深盘**: ≥2球
- **深盘**: 1球~球半(1.75)
- **中盘**: 半一(0.75)~一球(1.0)
- **浅盘**: 平半(0.25)~半球(0.5)
- **平手盘**: 0

### 第二步：按盘型匹配规则

#### A. 平手盘 (0)
- 开平手说明机构认为双方实力完全均等，**"主场优势"已被盘口否定**。
- **水位僵持识别（关键规则，针对布洛涅vs敦刻尔克2-6模式）**：如果平手盘初盘两端水位与即时盘几乎无变化（差异<0.05，如初盘0.99vs0.79→即时仍0.99vs0.79），说明市场完全均衡、机构无意引导任何一方。**此时严禁输出排除一个选项的双选（如胜/平、平/负），必须三选均保留≥15%概率，置信度上限55。** 市场均衡不等于平局倾向——它意味着任何极端赛果（包括一边倒大胜）都可能在机构认知范围内。
- 若低水方是客队 → 机构真实防范客胜，推客不败（平/负）
- 若低水方是主队但始终不升平半 → 极限诱主，警惕客胜爆冷
- 严禁仅因主场优势就推主不败

#### B. 浅盘 (平半~半球)
**核心问题: 机构为什么不敢开深？回答之前必须检查上盘是否有真实基本面支撑。**
- **主队基本面扎实 + 浅盘中低水(0.85~0.95)**：如果主队近期状态、主场战绩、交锋均占优，且盘口水位并非极低（≥0.85），**浅盘本身并非陷阱**，而是机构对主队优势的真实定价。此时应尊重基本面，推主不败(胜/平)，切忌机械反打。
- **主队基本面差、无底气** + 只开浅盘 → 浅盘引流诱上，坚决防冷看下盘
- 平半高水(>1.00)持续至临场 → 用高水阻上，推上盘不败
- 客队状态火爆/战意明确但只让平半 → 输半博全诱客陷阱，推主不败

#### C. 中盘 (半一~一球)
**核心区分: 阻上 vs 诱上**
- 半一满水（实力差距明显时）→ 阻上经典手法，高水恐吓，推上盘打穿
- 一球低水 + 主队火力猛 → 警惕"屠杀预期"陷阱，一球盘是赢球输盘重灾区，忌线性推演大胜
- 一球盘上盘水位不降反升 → 信心不足，防不胜爆冷
- **🔴 半一升一球 + 高水 → 造热假象，非真实阻上，坚决看下盘**: 此组合是"诱上"高危信号，机构利用升盘营造信心假象，同时用高水吸筹。**严禁将此类盘口变动解读为"阻上"——升盘+升水=盘水背离，是机构对让球方信心不足的铁证。** 若触发此模式必须降低让球方取胜概率至50%以下，优先推平局/客胜不败。

#### D. 深盘 (一球/球半~球半)
- 初盘开出即深盘 + 低水/降水 → 态度盘（阻上），推正路打穿
- 强队无战意/体能劣势但强开深盘 → 福利盘陷阱，看下盘
- 强队战意明确 + 深盘降水 → 虐菜模式，推让胜/让平
- **深盘高水清洗规则（针对周一002米亚尔比vs哈尔姆斯模式）**：主让一球/球半且水位≥0.95，如果主队NSPF赔率极低(<1.35)说明实力差距真实存在，此时高水≠看衰主队，而是机构用高水阻吓市场。**只能选"让胜/让平"，绝对禁止排除主胜推出"平/负"！**
- **深盘客让防主胜规则（针对周一001卡利亚里vs亚特兰大模式）**：当盘口为受半一或更深（受半一/受一球/受一球球半等），且客队NSPF赔率<1.60时，说明市场极度看好客队。但此场景下主队借助主场+受让保护，爆冷赢球的概率被严重低估！**本规则绝对禁止输出"平/负"双选（因为该双选不含"胜"，直接排除了已验证过的爆冷主胜场景）！** 必须输出含"胜"的推荐——保守选"胜/平"，激进选"胜/负"——但绝不能选"平/负"。置信度上限60。

#### E. 超深盘 (≥2球)
- 强队无积分压力开出两球半 → 战意归零表演赛风险，防赢球输盘或爆冷
- 客队争冠/保级战意 + 主队提前降级 + 两球半 → 极限诱上，防副班长尊严反弹

## 动态变化通用规则 (适用于所有盘型)
- **🔴 浅盘临场升水诱下判定 (04-30复盘新增，高危诱导)**: 针对“平手”、“平半”等浅盘口，当监测到临场阶段主队水位出现从低水区（≤0.85）向高水区（≥1.00）的剧烈攀升，且盘口未跟随调整时，**绝对不能直接给出“主队不胜”的强结论**。机构极大概率是利用“升水”这一表面利空形态，制造主队“让球无力”、“获胜不稳”的恐慌感，从而将热度驱赶至客队方向（平/负）。遇到此预警，必须强制触发风险复审，增加对主队获胜的考量权重，首选主队不败（胜/平）。
- **🔴 浅盘升水/高水的真实阻力判定 (针对平手/平半/半球盘，最高优先级)**: 当浅盘出现主队升水或维持高水时，严禁简单判定为“诱上”或“不看好”。必须强制判断：“是否存在明确的客队利好消息驱动（如主队核心伤停、客队交锋碾压）？”如果在基本面中找不到能压倒主队的利空消息，则必须将此盘口视为**“机构制造主队不稳的假象，实施真实阻力（吓退买入主队的资金）”**。**在此场景下，绝对禁止直接给出“平/负”的结论，必须保留主胜选项（胜/平）！**
- **升盘**: 初盘合理 + 升盘配低水 = 真实阻上；初盘已高开 + 继续升盘 = 诱上
- **🔴 升盘+升水背离 (04-28复盘新增高优先级规则)**: 当盘口升盘（如半一→一球、一球→一球/球半）但让球方水位同步抬升（≥0.05）时，此为"盘水背离"信号——升盘本应伴随降水位，水位反升说明机构并不真正看好让球方。**此时必须判定为"诱上"而非"阻上"，坚决走下盘。** 此规则在半一→一球和半球→半一的整数盘升级场景中触发率最高。若水位升幅≥0.08，直接排除让球方取胜，推平/负双选。
- **退盘**: 临场退盘+中高水 = 真实不看好；早盘退盘+低水回落 = 散热
- **退盘+基本面利空(伤停/轮换)可对应** → 真实风险，非诱盘
- **退盘诱下（与"退盘看衰"相反的高危陷阱）**：当一支名牌球队（如切尔西、马竞）近期状态不稳、市场舆论普遍不信任时，若盘口从半一退半球并维持高水，**这往往是机构利用市场恐慌吸筹下盘，而非真实看衰上盘！** 在此场景下，退盘+高水=诱下的经典组合，必须反向推主胜或上盘不败。
- **示弱反打（高位核心规则，直接针对近期最高频错误模式）**：当主队盘口出现下列"示弱"信号时，**严禁线性推导"主队不胜"**：
  - 主让半球低水→临场升水至中高水(>0.90)
  - 主让半一/一球，临场主队水位维持中高水(0.92~1.00)但未退盘
  - 客队让球临场降水
  **这些信号在五大联赛（意甲/英超/德甲/西甲/法甲/葡超）中，往往是机构利用"主队不稳"的公众认知进行反向吸筹（诱下），而非真实看衰主队。** 遇到上述信号+主队基本面不差（近期主场战绩尚可、无核心伤停），必须保持主胜不低于40%概率，首选"胜/平"而非"平/负"！

## 🚨 资金异动强制干预指令 (04-29复盘新增，最高优先级)
作为操盘手，当你看到输入数据中出现带 `🔴` 或 `🚨` 的【资金异动预警】时，这意味着机构真实的资金流向已经暴露，**你必须无条件服从这些预警，推翻你基于名气和表面状态得出的基本面结论！**
1. **半球生死盘异常**：如果看到上盘水位异常飙升的预警，说明大众资金在盲目追捧强队，机构在诱导。**坚决防范下盘直接赢球（客胜），严禁单选强队胜！** 如果看到升盘且降水的预警，说明机构在真实阻挡买入，**抛弃诱盘阴谋论，直接单选强队胜！**
2. **超深盘死水陷阱**：如果在球半/两球及以上的超深盘中看到“死水一潭”的预警，说明机构在诱导买入强队。这极易打出冷平或冷负，**绝对禁止在不让球玩法中单选强队胜，必须防平局！**
3. **二线联赛虚假繁荣**：如果在非五大联赛中看到“盘水背离（升盘不降水）”预警，这是典型的造热诱导，**必须坚决走下盘防冷！**

---

## 🟢 P2 场景辅助 (特定条件下触发调整)

- **联赛校准**: 美职联/澳超/荷甲 → "深盘防穿"不适用，攻击力碾压时敢推大比分。西甲/法乙/葡超 → 防守DNA，深盘优先防小球和赢球输盘
- **跨洲/跨国俱乐部杯赛 (亚冠/解放者杯/欧联杯/欧协联等)**: 必须大幅调高【主场优势】和【客场劣势】的权重。这类比赛常伴随极长飞行距离、跨气候带甚至高海拔（如南美）。主场胜率通常远超本土联赛。**【极高风险交叉标签】**：当此类杯赛遭遇浅盘（平手/平半/半球）时，信息极度不对称！严禁因为主队水位偏高就判定为“诱盘”。此时必须强制降低整体预测置信度（<50%），**绝对禁止单选，并且必须把“胜”包含在内（如胜/平）**，防范主队利用盘口示弱反杀。
- **主流联赛水位敏感度**: 意甲/英超/德甲/西甲/法甲/葡超 → 盘口升水或客队降水**不一定是真实看衰**，这些联赛中机构常用"示弱"手法诱下，主胜抗干扰能力强，严禁仅凭水位方向就排除主胜
- **赛季末战意**: 提前夺冠/保级/降级 → 战意归零；保级队面对绝对强队时，实力鸿沟优先于战意
- **双线作战**: 豪门周中欧战后 → 降大胜预期，防赢球输盘而非直接输球
- **德比/死敌**: 实力差距强制压缩，受让方和平局权重调高
- **换帅首战**: 前2场防守专注度极高加成
- **防线核心伤停**: 丢球概率飙升，不利小球

---

## Output Format (必须严格遵守以下格式，一字不差!)

- **【赛事概览与风险分级】**：一句话背景 + 风险等级

- **【基本面剖析】**：战意-状态评估，必须列出至少1条明确证据。若有伤停信息（尤其是雷速体育的伤停数据），**必须在此处明确列出对核心球员的影响**。若满足以下条件之一，在此处加 `🚨【高风险场次预警】`：①最高选项概率<55% ②深盘(≥1.5球)+强队体能/战意存疑 ③赛季前5轮或数据缺失 ④杯赛战意不对称

- **【盘赔深度解析】**：盘型定位（属于P1的哪一类）+ 机构意图推演 + 是否触发冷门预警。必须使用"诱上""阻上"等博弈术语。

- **【核心风控提示】**：本场最大不确定因素

- **🎯 最终预测**：
   - **竞彩推荐**：[胜/平/负，双选带权重如平(50%)/负(50%)] ——不让球推荐，**绝对禁止全包（三选），最多只能双选**。
   - **竞彩让球推荐**：[让胜/让平/让负，双选带权重] ——让球推荐，**绝对禁止全包（三选），最多只能双选**。
   - **竞彩置信度**：[0-100] (<60须双选防冷)
   - **⚽ 进球数参考**：[1-2个进球数，如2,3球]
   - **比分参考**：[2个比分，如1:0,1:1]
   - **进球数置信度**：[0-100]
"""


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
        :param match_data: 比赛数据
        :param period: 时间段标识 ('pre_24h', 'pre_12h', None自动判断)
        :param total_matches_count: 当日总比赛场数，用于辅助交叉盘风险判断
        :param is_sfc: 是否为胜负彩比赛，控制竞彩赔率等信息的显示
        :param other_matches_context: 其他相关比赛的数据，用于辅助交叉盘或多场同时间同联赛比赛的风控
        """
        # 自动判断时间段
        if period is None:
            period = self._determine_prediction_period(match_data)
            
        user_content = self._format_match_data(match_data, is_sfc=is_sfc)
        
        # 增加交叉盘/单日少赛事风险预警，并将其他比赛作为上下文透传
        if total_matches_count is not None and total_matches_count <= 3:
            user_content += f"\n\n🚨 **【高危预警：极端赛程交叉盘风险】** 🚨\n"
            user_content += f"注意：今天竞彩官方一共只开售了 {total_matches_count} 场比赛！\n"
            user_content += "根据国内主任操盘的经典规律，当单日比赛极少（特别是只有2场）时，全国资金会高度集中，极易触发“交叉盘”专杀2串1的剧本（即“送一场，杀一场”，一场正路顺利打出，另一场大热必死）。\n"
            user_content += "请在本次预测中**强制引入此交叉盘风控**！我将为你提供今日同开售的其他比赛的简要信息。你需要对比当前比赛与其他比赛的赔率、让球深度和基本面热度。如果当前比赛是最大的“大热比赛”，请务必审视其异常盘口或水位，大幅提高冷门预测权重；不要两场比赛都轻易给出双热正路的推荐结论！\n"
            
            if other_matches_context:
                user_content += "\n**【今日同开售的其他比赛上下文参考】**：\n"
                for i, om in enumerate(other_matches_context):
                    if om.get('match_num') != match_data.get('match_num'):
                        user_content += f"赛事 {i+1}: [{om.get('match_num')}] {om.get('league')} | {om.get('home_team')} VS {om.get('away_team')}\n"
                        om_odds = om.get('odds', {})
                        if om_odds.get('nspf'):
                            user_content += f"  - 不让球赔率: {om_odds.get('nspf')}\n"
                        if om_odds.get('spf'):
                            user_content += f"  - 让球({om_odds.get('rangqiu')})赔率: {om_odds.get('spf')}\n"
                        om_asian = om.get('asian_odds', {})
                        if 'macau' in om_asian:
                            user_content += f"  - 澳门亚指: {om_asian['macau'].get('start')} -> {om_asian['macau'].get('live')}\n"
                user_content += "请基于上述同日比赛的赔率结构，判断本场比赛在“交叉盘”剧本中，扮演的是“稳穿的正路”还是“杀猪的诱盘下路”！\n"

        # 增加胜负彩专属提示词
        if is_sfc:
            user_content += f"\n\n🚨 **【胜负彩专属要求】** 🚨\n"
            user_content += "这是一场足彩十四场（胜负彩）比赛，你需要预测的最终赛果是全场胜平负（不让球）。\n"
            user_content += "但是！【极其重要】：如果本场比赛提供了竞彩的【让球赔率(spf)】或【亚洲让球盘口】，你**必须**像分析普通竞彩一样，深度剖析这个让球盘口背后的机构博弈意图（诱盘、阻盘、强力看好等）。\n"
            user_content += "盘口深度和水位的异动是判断两队真实差距和爆冷可能性的核心维度，绝对不能因为这是胜负彩就忽略让球数据！\n"
            user_content += "区别仅仅在于：**在最终输出推荐时，只提供【竞彩不让球推荐】即可，不需要在输出结果中包含让球胜平负的选项**。你的推理过程必须包含让球博弈的思考！\n"

        logger.info(f"正在向大模型 ({self.model}) 发送预测请求：{match_data.get('home_team')} VS {match_data.get('away_team')} [时间段: {period}]")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"请分析以下比赛数据并给出预测：\n\n{user_content}"}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            result = response.choices[0].message.content
            logger.info(f"预测成功返回！ [时间段: {period}]")
            return result, period
            
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            return f"预测失败: {e}", period

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
