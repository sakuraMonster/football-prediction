import streamlit as st
import json
import os
import pandas as pd
import sys
import base64
from src.constants import AUTH_TOKEN_TTL
import time
from datetime import datetime, timedelta

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.llm.bball_predictor import BBallPredictor
from src.db.database import Database
from src.crawler.jclq_crawler import JclqCrawler
from src.crawler.nba_stats_crawler import NBAStatsCrawler

def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        username, timestamp = raw.split('|')
        return username, int(timestamp)
    except:
        return None, 0

# ==========================================
# 路由守卫：尝试从 URL Params 恢复登录状态
# ==========================================
if "auth" in st.query_params and not st.session_state.get("logged_in", False):
    try:
        token = st.query_params["auth"]
        username, login_timestamp = decode_auth_token(token)
        
        if username and (int(time.time()) - login_timestamp <= AUTH_TOKEN_TTL):
            db = Database()
            user = db.get_user(username)
            db.close()
            
            if user and datetime.now() <= user.valid_until:
                st.session_state["logged_in"] = True
                st.session_state["username"] = user.username
                st.session_state["role"] = user.role
                st.session_state["valid_until"] = user.valid_until
    except Exception as e:
        pass

if not st.session_state.get("logged_in", False):
    st.warning("⚠️ 您尚未登录或会话已过期，请先登录！")
    if st.button("👉 返回登录页面"):
        st.switch_page("app.py")
    st.stop() # 停止渲染下方内容
# ==========================================

# 设置页面配置
st.set_page_config(
    page_title="泊松数据模型 - 竞彩篮球",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 隐藏 Streamlit 默认的侧边栏页面导航
hide_pages_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
    </style>
"""
st.markdown(hide_pages_style, unsafe_allow_html=True)

# 加载数据
@st.cache_data(ttl=300) # 缓存5分钟
def load_bball_data():
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "today_bball_matches.json")
    if not os.path.exists(data_path):
        return []
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"加载篮球数据失败: {e}")
        return []

def save_bball_data(matches):
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "today_bball_matches.json")
    try:
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"保存篮球数据失败: {e}")

def main():
    st.title("🏀 竞彩篮球预测看板")
    st.caption("基于深度大语言模型的篮球赛事多维度推理与盘口分析系统")
    
    # 侧边栏导航
    st.sidebar.title("🧭 导航")
    
    # 导航按钮
    if st.sidebar.button("⚽ 返回今日赛事看板", use_container_width=True):
        if "auth" in st.query_params:
            st.switch_page("pages/1_Dashboard.py")
        elif "username" in st.session_state:
            try:
                raw_token = f"{st.session_state['username']}|{int(time.time())}"
                token = base64.b64encode(raw_token.encode('utf-8')).decode('utf-8')
                st.query_params["auth"] = token
            except:
                pass
            st.switch_page("pages/1_Dashboard.py")
        else:
            st.switch_page("pages/1_Dashboard.py")
        
    st.sidebar.button("🏀 竞彩篮球预测", type="primary", use_container_width=True)
    
    if st.sidebar.button("🔍 赛果复盘与模型优化", use_container_width=True):
        if "auth" in st.query_params:
            st.switch_page("pages/2_Post_Mortem.py")
        elif "username" in st.session_state:
            try:
                raw_token = f"{st.session_state['username']}|{int(time.time())}"
                token = base64.b64encode(raw_token.encode('utf-8')).decode('utf-8')
                st.query_params["auth"] = token
            except:
                pass
            st.switch_page("pages/2_Post_Mortem.py")
        else:
            st.switch_page("pages/2_Post_Mortem.py")
        
    st.sidebar.divider()
    
    # 用户信息展示
    st.sidebar.markdown(f"**👤 当前用户:** {st.session_state.get('username')}")
    st.sidebar.markdown(f"**🏷️ 角色:** {st.session_state.get('role')}")
    valid_until = st.session_state.get("valid_until")
    if valid_until:
        if isinstance(valid_until, str):
            try:
                valid_until = datetime.fromisoformat(valid_until)
            except ValueError:
                pass
        if isinstance(valid_until, datetime):
            st.sidebar.markdown(f"**⏳ 有效期至:** {valid_until.strftime('%Y-%m-%d')}")
        else:
             st.sidebar.markdown(f"**⏳ 有效期至:** {valid_until}")
             
    if st.sidebar.button("🚪 退出登录"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.switch_page("app.py")

    # ==========================
    # 主体内容区域
    # ==========================
    
    matches = load_bball_data()
    
    # 控制面板
    col1, col2 = st.columns([2, 1])
    with col1:
        st.metric("今日篮球赛事总数", len(matches))
        
    with col2:
        if 'expand_all' not in st.session_state:
            st.session_state.expand_all = False
        
        if st.button("展开/折叠 所有比赛详情", use_container_width=True):
            st.session_state.expand_all = not st.session_state.expand_all
            st.rerun()

    # 全局重新预测功能 (仅 Admin)
    if st.session_state.get("role") == "admin":
        st.markdown("### ⚙️ 数据抓取与预测控制")
        time_options = ["全部时间段", "凌晨 (00:00-08:00)", "白天 (08:00-16:00)", "傍晚 (16:00-20:00)", "晚场 (20:00-24:00)", "自定义时间段"]
        
        col_t1, col_t2 = st.columns([1, 2])
        with col_t1:
            selected_time = st.selectbox("按开赛时间段过滤拉取", time_options)
            
        custom_start_h = 0
        custom_end_h = 24
        if selected_time == "自定义时间段":
            with col_t2:
                # 使用 slider 选择小时范围
                time_range = st.slider(
                    "选择开赛时间范围 (小时)",
                    min_value=0, max_value=24,
                    value=(0, 24),
                    step=1
                )
                custom_start_h, custom_end_h = time_range
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("🚀 重新拉取数据并全局预测 (篮球)", type="primary", use_container_width=True):
                time_msg = selected_time if selected_time != "自定义时间段" else f"{custom_start_h}:00 - {custom_end_h}:00"
                with st.spinner(f"正在从500网拉取 {time_msg} 的最新篮球赛事数据，并调用大模型重新预测..."):
                    st.toast("正在抓取竞彩篮球列表...")
                    crawler = JclqCrawler()
                    new_matches = crawler.fetch_today_matches()
                    
                    if selected_time != "全部时间段":
                        if selected_time == "自定义时间段":
                            start_h, end_h = custom_start_h, custom_end_h
                        else:
                            ranges = {
                                "凌晨 (00:00-08:00)": (0, 8),
                                "白天 (08:00-16:00)": (8, 16),
                                "傍晚 (16:00-20:00)": (16, 20),
                                "晚场 (20:00-24:00)": (20, 24)
                            }
                            start_h, end_h = ranges[selected_time]
                            
                        filtered_new = []
                        for m in new_matches:
                            try:
                                hour = int(m.get('match_time', '').split(' ')[1].split(':')[0])
                                if start_h <= hour < end_h:
                                    filtered_new.append(m)
                            except:
                                filtered_new.append(m)
                        new_matches = filtered_new
                    
                    if not new_matches:
                        st.error(f"未能抓取到 {time_msg} 的篮球比赛数据，请稍后再试。")
                    else:
                        st.toast("正在抓取各球队最新伤停与战绩...")
                        stats_crawler = NBAStatsCrawler()
                        for m in new_matches:
                            if '美职篮' in m.get('league', ''):
                                m['away_stats'] = stats_crawler.get_team_stats(m.get('away_team'))
                                m['home_stats'] = stats_crawler.get_team_stats(m.get('home_team'))
                                
                        st.toast("正在全局重新调用大模型预测...")
                        predictor = BBallPredictor()
                        db = Database()
                        total_count = len(new_matches)
                        for m in new_matches:
                            res = predictor.predict(m, total_matches_count=total_count)
                            m["llm_prediction"] = res
                            db.save_bball_prediction(m)
                        db.close()
                        
                        load_bball_data.clear()
                        save_bball_data(new_matches)
                        st.success("最新篮球赛事数据已拉取并全局预测完成！")
                        time.sleep(1)
                        st.rerun()
                        
        with col_btn2:
            if st.button("🚀 仅对当前篮球数据全局重新预测", use_container_width=True):
                with st.spinner("正在抓取最新基本面并调用大模型重新预测，请耐心等待..."):
                    stats_crawler = NBAStatsCrawler()
                    predictor = BBallPredictor()
                    db = Database()
                    total_count = len(matches)
                    for m in matches:
                        if '美职篮' in m.get('league', ''):
                            m['away_stats'] = stats_crawler.get_team_stats(m.get('away_team'))
                            m['home_stats'] = stats_crawler.get_team_stats(m.get('home_team'))
                        res = predictor.predict(m, total_matches_count=total_count)
                        m["llm_prediction"] = res
                        db.save_bball_prediction(m)
                    db.close()
                    load_bball_data.clear()
                    save_bball_data(matches)
                    st.success("全局篮球重新预测完成！")
                    time.sleep(1)
                    st.rerun()

    # 汇总预测结果看板
    st.markdown("---")
    st.subheader("📋 今日篮球赛事预测汇总")
    
    summary_data = []
    for match in matches:
        prediction_text = match.get("llm_prediction", "")
            
        if prediction_text:
            details = BBallPredictor.parse_prediction_details(prediction_text)
            
            confidence_str = details.get('confidence', '0')
            import re
            conf_match = re.search(r'\d+', confidence_str)
            conf_score = int(conf_match.group()) if conf_match else 0
            
            summary_data.append({
                "编号": match.get('match_num', ''),
                "赛事": match.get('league', ''),
                "客队": match.get('away_team', ''),
                "主队": match.get('home_team', ''),
                "开赛时间": match.get('match_time', ''),
                "让分推荐": details.get('recommendation', '无'),
                "大小分推荐": details.get('dxf_recommendation', '无'),
                "置信度": confidence_str,
                "基础理由": details.get('reason', '无'),
                "_sort_score": conf_score
            })
            
    if summary_data:
        summary_data = sorted(summary_data, key=lambda x: x["_sort_score"], reverse=True)
        display_data = [{k: v for k, v in d.items() if k != "_sort_score"} for d in summary_data]
        df_summary = pd.DataFrame(display_data)
        st.dataframe(df_summary, use_container_width=True)
        
        # 智能串单推荐功能
        st.markdown("### 🎫 AI 智能串关推荐 (篮球)")
        if 'bball_generated_parlays' not in st.session_state:
            st.session_state.bball_generated_parlays = None
            
        col_gen, col_clear = st.columns([2, 8])
        with col_gen:
            if st.button("🏀 生成篮球智能串关方案", type="primary"):
                with st.spinner("正在根据今日数据和风险模型计算最优串关方案..."):
                    predictor = BBallPredictor()
                    st.session_state.bball_generated_parlays = predictor.generate_parlays(display_data)
        
        with col_clear:
            if st.session_state.bball_generated_parlays:
                if st.button("清除方案"):
                    st.session_state.bball_generated_parlays = None
                    st.rerun()
                    
        if st.session_state.bball_generated_parlays:
            with st.expander("🎫 AI 智能串关方案", expanded=True):
                st.success("✅ 篮球串子单生成完毕！请参考：")
                st.markdown(st.session_state.bball_generated_parlays)
    else:
        st.info("暂无预测数据，请先运行预测。")

    st.markdown("---")
    st.subheader("📝 赛事详细分析列表")

    for match in matches:
        with st.expander(f"📌 {match.get('match_num')} | {match.get('league')} | {match.get('away_team')}(客) VS {match.get('home_team')}(主) | {match.get('match_time')}", expanded=st.session_state.expand_all):
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.subheader("🎫 竞彩官方让分盘")
                odds = match.get("odds", {})
                st.markdown(f"**官方预设让分:** {odds.get('rangfen', '无')}")
                st.markdown(f"**胜负赔率(客胜/主胜):** {odds.get('sf', ['-', '-'])}")
                st.markdown(f"**让分胜负(客/主):** {odds.get('rfsf', ['-', '-'])}")

            with col2:
                st.subheader("📈 竞彩官方大小分盘")
                st.markdown(f"**官方预设大小分:** {odds.get('yszf', '无')}")
                st.markdown(f"**大小分赔率(大分/小分):** {odds.get('dxf', ['-', '-'])}")

            st.subheader("🤖 大模型深度预测报告")
            
            prediction = match.get("llm_prediction", "")
            
            if st.session_state.get("role") == "admin":
                if st.button("🔄 重新预测此场比赛", key=f"repredict_{match.get('match_num')}"):
                    with st.spinner("正在抓取最新基本面并调用大模型重新预测..."):
                        stats_crawler = NBAStatsCrawler()
                        if '美职篮' in match.get('league', ''):
                            match['away_stats'] = stats_crawler.get_team_stats(match.get('away_team'))
                            match['home_stats'] = stats_crawler.get_team_stats(match.get('home_team'))
                            
                        predictor = BBallPredictor()
                        total_count = len(matches)
                        new_pred = predictor.predict(match, total_matches_count=total_count)
                        match["llm_prediction"] = new_pred
                        
                        db = Database()
                        db.save_bball_prediction(match)
                        db.close()
                        
                        load_bball_data.clear()
                        save_bball_data(matches)
                        
                        st.success("预测已更新！")
                        st.rerun()

            if prediction:
                if "Authentication Fails" in prediction or "预测失败" in prediction:
                    st.error(prediction)
                    st.info("提示: 请在 config/.env 文件中配置有效的 LLM_API_KEY。")
                else:
                    st.markdown(prediction)
            else:
                st.info("该场比赛尚未生成 AI 预测结果。")

if __name__ == "__main__":
    main()
