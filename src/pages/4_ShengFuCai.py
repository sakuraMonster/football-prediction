import streamlit as st
import json
import os
import sys
import time
import base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.constants import AUTH_TOKEN_TTL
from datetime import datetime
from loguru import logger
import traceback

from src.db.database import Database
from src.crawler.sfc_crawler import SfcCrawler
from src.crawler.odds_crawler import OddsCrawler
from src.llm.predictor import LLMPredictor

# ==========================================
# 辅助函数
# ==========================================
def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        username, timestamp = raw.split('|')
        return username, int(timestamp)
    except:
        return None, 0

@st.cache_data(ttl=3600)
def fetch_sfc_issues():
    """获取可用的胜负彩期号列表"""
    crawler = SfcCrawler()
    return crawler.fetch_available_issues()

@st.cache_data(ttl=3600)
def fetch_sfc_data(issue_number=None):
    """抓取最新的胜负彩数据并缓存1小时，同时尝试获取竞彩赔率信息"""
    crawler = SfcCrawler()
    matches = crawler.fetch_current_issue(issue_number)
    
    # 尝试将竞彩赔率（如果有的话）合并进去
    try:
        from src.crawler.jingcai_crawler import JingcaiCrawler
        jc_crawler = JingcaiCrawler()
        jc_matches = jc_crawler.fetch_today_matches()
        # 建立 fixture_id 映射
        jc_dict = {m.get("fixture_id"): m for m in jc_matches if m.get("fixture_id")}
        
        for m in matches:
            fid = m.get("fixture_id")
            if fid and fid in jc_dict:
                m["odds"] = jc_dict[fid].get("odds", {})
    except Exception as e:
        logger.warning(f"合并竞彩赔率到胜负彩数据时出错: {e}")
        
    return matches

def predict_single_sfc_match(match, db):
    """预测单场胜负彩比赛"""
    odds_crawler = OddsCrawler()
    fixture_id = match.get("fixture_id")
    match_num = match.get("match_num")
    
    if fixture_id:
        st.toast(f"正在抓取 {match_num} 基本面数据...", icon="⏳")
        match_details = odds_crawler.fetch_match_details(fixture_id)
        # 将结构展开，和 DataFusion 保持一致
        match["asian_odds"] = match_details.get("asian_odds", {})
        match["recent_form"] = match_details.get("recent_form", {})
        match["h2h_summary"] = match_details.get("h2h_summary", "")
    else:
        st.toast(f"{match_num} 无比赛ID，跳过基本面抓取", icon="⚠️")
    
    st.toast(f"正在分析 {match_num}...", icon="🧠")
    predictor = LLMPredictor()
    prediction_result, _ = predictor.predict(match, is_sfc=True)
    
    if prediction_result:
        try:
            match["llm_prediction"] = prediction_result
            # 保存到数据库
            db.save_sfc_prediction(match)
            return True, prediction_result
        except Exception as e:
            return False, f"保存数据库失败: {str(e)}"
    return False, "预测生成失败"

# ==========================================
# 页面主逻辑
# ==========================================
def main():
    st.set_page_config(page_title="胜负彩14场预测", page_icon="🎯", layout="wide")
    
    # 隐藏导航栏
    hide_pages_style = """
        <style>
            [data-testid="stSidebarNav"] {display: none;}
        </style>
    """
    st.markdown(hide_pages_style, unsafe_allow_html=True)
    
    # 路由守卫
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
        st.stop()

    # 导航侧边栏
    st.sidebar.header("🧭 功能导航")
    
    if st.sidebar.button("⚽ 竞彩足球预测", use_container_width=True):
        st.switch_page("pages/1_Dashboard.py")
        
    if st.sidebar.button("🏀 竞彩篮球预测", use_container_width=True):
        st.switch_page("pages/3_Basketball.py")
        
    if st.sidebar.button("🔍 赛果复盘与模型优化", use_container_width=True):
        st.switch_page("pages/2_Post_Mortem.py")
        
    st.sidebar.markdown("---")
    st.sidebar.info(f"当前用户: {st.session_state.get('username')}")
    if st.sidebar.button("退出登录", use_container_width=True):
        st.session_state["logged_in"] = False
        st.rerun()

    # 页面主体
    st.title("🎯 足彩十四场 (胜负彩) 智能预测")
    st.markdown("选择期号抓取足彩十四场赛事，并利用 AI 模型进行全场胜平负深层博弈分析。")
    
    # 抓取可用期号
    with st.spinner("正在获取期号列表..."):
        issues = fetch_sfc_issues()
        
    if not issues:
        st.warning("暂未获取到胜负彩期号，尝试直接拉取最新数据...")
        selected_issue = None
    else:
        # 下拉框选择期号
        selected_issue = st.selectbox(
            "📍 选择胜负彩期号", 
            options=issues,
            format_func=lambda x: f"第 {x} 期"
        )
    
    # 抓取数据
    with st.spinner(f"正在拉取 {selected_issue if selected_issue else '最新'} 赛事..."):
        matches = fetch_sfc_data(selected_issue)
        
    if not matches:
        st.error("未能获取到该期的胜负彩赛事，请稍后再试或检查爬虫日志。")
        if st.button("🔄 强制刷新缓存"):
            fetch_sfc_issues.clear()
            fetch_sfc_data.clear()
            st.rerun()
        st.stop()
        
    issue_num = matches[0].get("issue_num", "未知期号")
    st.info(f"**当前抓取期号：** {issue_num} | **包含比赛：** {len(matches)} 场")
    
    # 全局控制
    col1, col2, col3 = st.columns([1.5, 1.5, 1])
    with col1:
        if st.button("🚀 一键推演全部 14 场 (跳过已分析)", type="primary", use_container_width=True):
            st.session_state["auto_predict_sfc"] = True
            st.session_state["force_repredict_all"] = False
            st.rerun()
    with col2:
        if st.button("🔄 强制重新推演全部 14 场", type="secondary", use_container_width=True):
            st.session_state["auto_predict_sfc"] = True
            st.session_state["force_repredict_all"] = True
            st.rerun()
    with col3:
        if st.button("🔄 刷新赛事数据", use_container_width=True):
            fetch_sfc_data.clear()
            st.rerun()
            
    db = Database()
    
    # 自动预测逻辑
    if st.session_state.get("auto_predict_sfc", False):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        force_repredict = st.session_state.get("force_repredict_all", False)
        
        for i, match in enumerate(matches):
            status_text.text(f"正在分析 ({i+1}/{len(matches)}): {match['home_team']} vs {match['away_team']}")
            
            # 检查是否已预测过
            existing = db.get_sfc_prediction(issue_num, match['match_num'])
            if existing and not force_repredict:
                logger.info(f"[{match['match_num']}] 已存在预测结果，跳过")
            else:
                success, msg = predict_single_sfc_match(match, db)
                if not success:
                    st.error(f"第 {i+1} 场分析失败: {msg}")
                    
            progress_bar.progress((i + 1) / len(matches))
            time.sleep(1) # 适当延时防止请求过快
            
        status_text.text("✅ 14场比赛全部分析完毕！")
        st.session_state["auto_predict_sfc"] = False
        st.session_state["force_repredict_all"] = False
        st.success("🎉 全部 14 场比赛预测完成！")
        st.rerun()
        
    # 赛事列表展示
    st.markdown("### 📋 赛事列表与分析结果")
    
    for i, match in enumerate(matches):
        match_num = match["match_num"]
        home_team = match["home_team"]
        away_team = match["away_team"]
        league = match["league"]
        
        # 查询数据库中是否已有结果
        existing_pred = db.get_sfc_prediction(issue_num, match_num)
        
        # 提取推荐结果 (如果存在)
        recommendation = "待预测"
        pred_color = "gray"
        
        if existing_pred:
            pred_text = existing_pred.prediction_text if existing_pred.prediction_text else ""
            # 使用标准的解析方法提取推荐
            details = LLMPredictor.parse_prediction_details(pred_text)
            rec_nspf = details.get('recommendation_nspf', '')
            
            if rec_nspf:
                recommendation = rec_nspf
                pred_color = "green" if "胜" in recommendation else ("blue" if "平" in recommendation else "red")
            else:
                # 兼容直接正则匹配失败的情况
                import re
                nspf_match = re.search(r'\*\*竞彩不让球推荐[：:]\*\*\s*【?(.*?)】?', pred_text)
                if nspf_match:
                    recommendation = nspf_match.group(1).replace('*', '').strip()
                    pred_color = "green" if "胜" in recommendation else ("blue" if "平" in recommendation else "red")
                else:
                    recommendation = "已分析 (需点开查看)"
                    pred_color = "black"
                
        with st.expander(f"[{i+1}] {league} | **{home_team}** vs **{away_team}** | 预测: :{pred_color}[{recommendation}]"):
            st.write(f"**比赛时间:** {match['match_time']}")
            
            if existing_pred and existing_pred.prediction_text:
                st.markdown(existing_pred.prediction_text)
                if st.button(f"🔄 重新预测本场", key=f"repredict_{match_num}"):
                    success, msg = predict_single_sfc_match(match, db)
                    if success:
                        st.success("预测更新成功！")
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("本场比赛暂未进行分析。")
                if st.button(f"🧠 立即分析", key=f"predict_{match_num}"):
                    success, msg = predict_single_sfc_match(match, db)
                    if success:
                        st.success("分析完成！")
                        st.rerun()
                    else:
                        st.error(msg)
                        
    db.close()

if __name__ == "__main__":
    main()
