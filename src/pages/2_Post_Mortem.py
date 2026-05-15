import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import base64
import os
import sys
import json
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.constants import AUTH_TOKEN_TTL
import time
from src.db.database import Database
from src.crawler.jingcai_crawler import JingcaiCrawler
from src.llm.predictor import LLMPredictor
from src.utils.rule_drafts import get_pending_rule_drafts, replace_pending_rule_drafts_for_date

def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        username, timestamp = raw.split('|')
        return username, int(timestamp)
    except:
        return None, 0


def build_rule_manager_url(auth_token, focus_case="", focus_rule_id="", focus_scope="", focus_action=""):
    params = {}
    if auth_token:
        params["auth"] = auth_token
    if focus_case:
        params["focus_case"] = focus_case
    if focus_rule_id:
        params["focus_rule_id"] = focus_rule_id
    if focus_scope:
        params["focus_scope"] = focus_scope
    if focus_action:
        params["focus_action"] = focus_action
    query = urlencode(params)
    return f"/Rule_Manager?{query}" if query else "/Rule_Manager"

def main():
    st.set_page_config(page_title="赛果复盘与模型优化", page_icon="🔍", layout="wide")
    
    # 隐藏 Streamlit 默认的侧边栏页面导航
    hide_pages_style = """
        <style>
            [data-testid="stSidebarNav"] {display: none;}
        </style>
    """
    st.markdown(hide_pages_style, unsafe_allow_html=True)
    
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
                    st.session_state["auth_token"] = token
        except Exception as e:
            pass

    if not st.session_state.get("logged_in", False):
        st.warning("⚠️ 您尚未登录或会话已过期，请先登录！")
        if st.button("👉 返回登录页面"):
            st.switch_page("app.py")
        st.stop()
    
    # 确保 URL 中携带 auth token（防止直接访问 /Post_Mortem 时缺失）
    if "auth" not in st.query_params and "username" in st.session_state:
        token = st.session_state.get("auth_token", "")
        if not token:
            try:
                raw_token = f"{st.session_state['username']}|{int(time.time())}"
                token = base64.b64encode(raw_token.encode("utf-8")).decode("utf-8")
            except Exception:
                token = ""
        if token:
            st.session_state["auth_token"] = token
            st.query_params["auth"] = token
    # ==========================================
        
    # 显示当前登录用户信息
    st.sidebar.markdown("---")
    user_info = f"👤 当前用户: {st.session_state.get('username', '未知')} ({st.session_state.get('role', '').upper()})"
    if st.session_state.get('role') == 'vip' and 'valid_until' in st.session_state:
        valid_until = st.session_state['valid_until']
        if isinstance(valid_until, datetime):
            valid_date = valid_until.strftime('%Y-%m-%d')
        else:
            valid_date = str(valid_until).split(' ')[0]
        user_info += f"\n\n⏳ 到期时间: {valid_date}"
    st.sidebar.info(user_info)
    st.sidebar.markdown("---")

    current_auth_token = st.query_params.get("auth", "") or st.session_state.get("auth_token", "")

    st.sidebar.header("🧭 功能导航")
    if st.sidebar.button("🏠 返回今日赛事看板", use_container_width=True):
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

    if st.sidebar.button("🏀 竞彩篮球预测", use_container_width=True):
        if "auth" in st.query_params:
            st.switch_page("pages/3_Basketball.py")
        elif "username" in st.session_state:
            try:
                raw_token = f"{st.session_state['username']}|{int(time.time())}"
                token = base64.b64encode(raw_token.encode('utf-8')).decode('utf-8')
                st.query_params["auth"] = token
            except:
                pass
            st.switch_page("pages/3_Basketball.py")
        else:
            st.switch_page("pages/3_Basketball.py")

    st.title("🔍 赛果复盘与模型优化")
    st.markdown("通过抓取实际赛果与AI预测进行对比，自动总结得失，优化预测逻辑。")

    # 1. 选择日期
    col1, col2, col3, col4 = st.columns([1, 2, 2, 2])
    with col1:
        # 默认昨天
        default_date = datetime.now() - timedelta(days=1)
        target_date = st.date_input("选择复盘日期", value=default_date)
        target_date_str = target_date.strftime("%Y-%m-%d")

    db = Database()
    
    with col2:
        st.write("")
        st.write("")
        if st.button("🚀 获取该日赛果并比对", type="primary"):
            with st.spinner("正在从500网拉取当日赛果..."):
                crawler = JingcaiCrawler()
                # 我们之前在爬虫里增加了 fetch_match_results
                results_dict = crawler.fetch_match_results(target_date_str)
                if not results_dict:
                    st.warning(f"未能抓取到 {target_date_str} 的赛果，可能该日无比赛或比赛尚未出结果。")
                else:
                    # 抓取到了，更新到数据库
                    # 注意，数据库里的记录可以通过 match_num 来匹配，也可以通过 fixture_id。
                    predictions = db.get_predictions_by_date(target_date_str)
                    
                    # 为了只展示属于抓取赛果范围内的比赛，我们加一个过滤
                    matched_predictions = []
                    matched_fixture_ids = []
                    for p in predictions:
                        if p.match_num and p.match_num in results_dict:
                            result_info = results_dict[p.match_num]
                            actual_score = result_info.get("score")
                            actual_bqc = result_info.get("bqc_result")
                            
                            # 精准匹配：如果有时间信息，进一步比对时间
                            # 数据库中 p.match_time 是 datetime 对象
                            if p.match_time and result_info.get("match_time"):
                                db_time_str = p.match_time.strftime("%Y-%m-%d %H:%M")
                                if db_time_str != result_info.get("match_time"):
                                    continue # 时间不匹配，跳过
                                    
                            db.update_actual_result(p.fixture_id, actual_score, actual_bqc)
                            p.actual_score = actual_score # 立即更新内存对象，方便展示
                            p.actual_bqc = actual_bqc
                            matched_predictions.append(p)
                            matched_fixture_ids.append(p.fixture_id)
                            
                    st.session_state["post_mortem_date"] = target_date_str
                    st.session_state["post_mortem_fixture_ids"] = matched_fixture_ids
                    st.success(f"成功获取并更新了 {len(matched_predictions)} 场比赛的赛果！")
                    
    with col3:
        st.write("")
        st.write("")
        if st.button("📥 补拉历史比赛数据(仅入库)", help="从500彩票网历史页面拉取指定日期的比赛和比分（不走预测）"):
            with st.spinner(f"正在从500网拉取 {target_date_str} 历史数据..."):
                from src.processor.data_fusion import DataFusion, build_leisu_crawler
                from src.crawler.odds_crawler import OddsCrawler
                
                jingcai_crawler = JingcaiCrawler()
                history_matches = jingcai_crawler.fetch_history_matches(target_date)
                
                if not history_matches:
                    st.warning(f"未能拉取到 {target_date_str} 的历史比赛数据。")
                else:
                    st.toast(f"已拉取 {len(history_matches)} 场比赛，正在融合盘口数据...")
                    leisu = build_leisu_crawler(headless=True)
                    try:
                        odds_crawler = OddsCrawler()
                        data_fusion = DataFusion()
                        history_matches = data_fusion.merge_data(
                            history_matches,
                            odds_crawler,
                            leisu_crawler=leisu,
                        )
                    except Exception as e:
                        st.warning(f"盘口数据融合失败: {e}")
                    finally:
                        if leisu:
                            try:
                                leisu.close()
                            except Exception:
                                pass
                        
                    # 先清除该窗口内已有的 historical 记录，防止重复拉取导致数据翻倍
                    ws = datetime.strptime(target_date_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
                    we = (datetime.strptime(target_date_str, '%Y-%m-%d') + timedelta(days=1)).replace(hour=12, minute=0, second=0)
                    from sqlalchemy import text
                    db.session.execute(text("""
                        DELETE FROM match_predictions 
                        WHERE prediction_period = 'historical'
                          AND match_time >= :ws AND match_time < :we
                    """), {"ws": ws.strftime('%Y-%m-%d %H:%M:%S'), "we": we.strftime('%Y-%m-%d %H:%M:%S')})
                    
                    saved = 0
                    for m in history_matches:
                        try:
                            raw_json = json.dumps(m, ensure_ascii=False)
                            match_time = m.get('match_time', '')
                            db.session.execute(text("""
                                INSERT INTO match_predictions 
                                (fixture_id, match_num, league, home_team, away_team, match_time, 
                                 prediction_text, prediction_period, raw_data, actual_score, actual_bqc, created_at)
                                VALUES (:fid, :mn, :lg, :ht, :at, :mt, '', 'historical', :raw, :sc, :bqc, datetime('now'))
                            """), {
                                "fid": m.get('fixture_id'), "mn": m.get('match_num'),
                                "lg": m.get('league', ''), "ht": m.get('home_team', ''),
                                "at": m.get('away_team', ''), "mt": match_time,
                                "raw": raw_json, "sc": m.get('actual_score', ''), "bqc": m.get('bqc_result', '')
                            })
                            saved += 1
                        except Exception as e:
                            st.warning(f"保存 {m.get('match_num')} 失败: {e}")
                    db.session.commit()
                    st.success(f"✅ 成功补拉并入库 {saved}/{len(history_matches)} 场历史数据！请刷新页面查看。")
                    
    with col4:
        st.write("")
        st.write("")
        if st.button("🔄 对历史数据重新预测", help="对已拉取的历史补拉数据（prediction_period=historical）重新执行大模型预测"):
            window_start = datetime.combine(target_date, datetime.min.time()).replace(hour=12, minute=0, second=0)
            window_end = (datetime.combine(target_date, datetime.min.time()) + timedelta(days=1)).replace(hour=12, minute=0, second=0)
            
            from src.db.database import MatchPrediction
            hist_records = db.session.query(MatchPrediction).filter(
                MatchPrediction.prediction_period == 'historical',
                MatchPrediction.match_time >= window_start,
                MatchPrediction.match_time < window_end
            ).all()
            
            if not hist_records:
                st.warning(f"当前日期窗口 ({target_date_str} 12:00~次日12:00) 没有历史补拉数据，请先点击「补拉历史比赛数据」按钮。")
            else:
                st.toast(f"找到 {len(hist_records)} 条历史补拉记录，正在逐一调用大模型预测...")
                from src.processor.data_fusion import build_leisu_crawler, inject_leisu_data
                predictor = LLMPredictor()
                leisu = build_leisu_crawler(headless=True)
                success_count = 0
                fail_count = 0
                progress_bar = st.progress(0)
                
                for i, p in enumerate(hist_records):
                    try:
                        raw_data = p.raw_data or {}
                        if isinstance(raw_data, str):
                            raw_data = json.loads(raw_data)
                        if not isinstance(raw_data, dict):
                            raw_data = {}
                        
                        match_dict = dict(raw_data)
                        match_dict.update({
                            "fixture_id": p.fixture_id,
                            "match_num": p.match_num,
                            "league": p.league,
                            "home_team": p.home_team,
                            "away_team": p.away_team,
                            "match_time": str(p.match_time) if p.match_time else "",
                        })
                        match_dict.setdefault("odds", raw_data.get("odds", {}))
                        match_dict.setdefault("asian_odds", raw_data.get("asian_odds", {}))
                        match_dict.setdefault("recent_form", raw_data.get("recent_form", {}))
                        match_dict.setdefault("h2h_summary", raw_data.get("h2h_summary", "暂无"))
                        match_dict.setdefault("advanced_stats", raw_data.get("advanced_stats", {}))
                        if leisu:
                            inject_leisu_data(match_dict, leisu)
                        
                        pred_text, _ = predictor.predict(
                            match_dict,
                            period="repredicted",
                            total_matches_count=len(hist_records),
                        )
                        if pred_text and "预测失败" not in pred_text:
                            try:
                                predicted_result = Database.extract_prediction_recommendation(pred_text)
                                repredicted_record = db.session.query(MatchPrediction).filter(
                                    MatchPrediction.fixture_id == p.fixture_id,
                                    MatchPrediction.prediction_period == 'repredicted'
                                ).first()

                                if not repredicted_record:
                                    repredicted_record = MatchPrediction(
                                        fixture_id=p.fixture_id,
                                        match_num=p.match_num,
                                        league=p.league,
                                        home_team=p.home_team,
                                        away_team=p.away_team,
                                        match_time=p.match_time,
                                        prediction_period='repredicted',
                                        raw_data=match_dict,
                                    )
                                    db.session.add(repredicted_record)

                                repredicted_record.raw_data = match_dict
                                repredicted_record.prediction_text = pred_text
                                repredicted_record.predicted_result = predicted_result
                                repredicted_record.actual_score = p.actual_score
                                repredicted_record.actual_bqc = p.actual_bqc
                                repredicted_record.actual_result = p.actual_result
                                repredicted_record.htft_prediction_text = p.htft_prediction_text
                                p.raw_data = match_dict
                                db.session.commit()
                                success_count += 1
                            except Exception as e:
                                db.session.rollback()
                                fail_count += 1
                                st.warning(f"{p.match_num} 保存失败: {e}")
                        else:
                            fail_count += 1
                            st.warning(f"{p.match_num} 预测失败: {pred_text}")
                    except Exception as e:
                        fail_count += 1
                        st.warning(f"{p.match_num} 预测异常: {e}")
                    
                    progress_bar.progress((i + 1) / len(hist_records))

                if leisu:
                    try:
                        leisu.close()
                    except Exception:
                        pass
                progress_bar.empty()
                if success_count > 0:
                    st.success(f"✅ 成功重新预测 {success_count}/{len(hist_records)} 场历史比赛！请刷新页面查看结果。")
                if fail_count > 0:
                    st.error(f"❌ {fail_count} 场预测失败")
            
    # 2. 展示比对结果
    st.divider()
    st.subheader(f"📋 {target_date_str} 预测与赛果汇总")
    
    # 优先展示刚才拉取匹配到的比赛，否则重新查询（可能包含没打完的）
    if st.session_state.get("post_mortem_date") == target_date_str and st.session_state.get("post_mortem_fixture_ids"):
        fixture_ids = set(st.session_state["post_mortem_fixture_ids"])
        predictions = [p for p in db.get_predictions_by_date(target_date_str) if p.fixture_id in fixture_ids]
    else:
        predictions = db.get_predictions_by_date(target_date_str)
        
    if not predictions:
        st.info("该日期没有找到任何预测记录。")
    else:
        table_data = []
        for p in predictions:
            details = LLMPredictor.parse_prediction_details(p.prediction_text) if p.prediction_text else {}
            
            rec_nspf = details.get('recommendation_nspf', '暂无') if details else '暂无'
            rec_rq = details.get('recommendation_rq', '暂无') if details else '暂无'
            reason = details.get('reason', '无') if details else '无'
            
            # 解析半全场预测（仅用于后续 tab 中半全场复盘，不在主表展示）
            htft_text = p.htft_prediction_text if hasattr(p, 'htft_prediction_text') and p.htft_prediction_text else ""
            htft_rec = "无"
            if htft_text:
                import re
                rec_match = re.search(r'半全场单关推荐[^\n]*?[:：]\s*\[?(.*?)\]?(?=\n|$)', htft_text)
                if rec_match:
                    htft_rec = rec_match.group(1).replace('[', '').replace(']', '').replace('**', '').strip()
            
            bqc_map = {
                '3-3': '胜胜', '3-1': '胜平', '3-0': '胜负',
                '1-3': '平胜', '1-1': '平平', '1-0': '平负',
                '0-3': '负胜', '0-1': '负平', '0-0': '负负'
            }
            actual_bqc_cn = bqc_map.get(p.actual_bqc, p.actual_bqc) if hasattr(p, 'actual_bqc') and p.actual_bqc else "未知"
            
            table_data.append({
                "编号": p.match_num,
                "赛事": p.league,
                "主队": p.home_team,
                "客队": p.away_team,
                "不让球推荐": rec_nspf if rec_nspf != '暂无' else '无',
                "让球推荐": rec_rq if rec_rq != '暂无' else '无',
                "实际比分": p.actual_score if p.actual_score else "未知",
                "全场理由": reason,
                "_raw_record": p,
                "_htft_rec": htft_rec,
                "_actual_bqc_cn": actual_bqc_cn
            })
            
        df = pd.DataFrame(table_data)
        st.dataframe(df.drop(columns=["_raw_record", "_htft_rec", "_actual_bqc_cn"]), use_container_width=True, hide_index=True)

        if st.session_state.get("role") == "admin":
            st.markdown("### 🔁 重新预测当前列表比赛")
            opt_cols = st.columns([1.2, 1.2, 1.9, 1.0])
            only_incorrect = opt_cols[0].checkbox(
                "仅重跑未命中",
                value=False,
                key=f"pm_repredict_only_incorrect_{target_date_str}",
            )
            use_leisu = opt_cols[1].checkbox(
                "注入雷速情报",
                value=True,
                key=f"pm_repredict_use_leisu_{target_date_str}",
            )
            auto_update_review = opt_cols[2].checkbox(
                "完成后自动更新复盘报告",
                value=False,
                key=f"pm_repredict_auto_review_{target_date_str}",
            )
            if opt_cols[3].button("开始重新预测", key=f"pm_btn_repredict_current_{target_date_str}"):
                from src.db.database import MatchPrediction
                from src.processor.data_fusion import build_leisu_crawler, inject_leisu_data

                candidates = list(predictions)
                if only_incorrect:
                    filtered = []
                    for p in candidates:
                        is_correct = getattr(p, "is_correct", None)
                        if is_correct is False:
                            filtered.append(p)
                    candidates = filtered

                if not candidates:
                    st.warning("当前没有可重新预测的比赛记录。")
                else:
                    predictor = LLMPredictor()
                    leisu = build_leisu_crawler(headless=True) if use_leisu else None
                    success_count = 0
                    fail_count = 0
                    progress_bar = st.progress(0)
                    for i, p in enumerate(candidates):
                        try:
                            raw_data = getattr(p, "raw_data", None) or {}
                            if isinstance(raw_data, str):
                                raw_data = json.loads(raw_data)
                            if not isinstance(raw_data, dict):
                                raw_data = {}

                            match_dict = dict(raw_data)
                            match_dict.update(
                                {
                                    "fixture_id": p.fixture_id,
                                    "match_num": p.match_num,
                                    "league": p.league,
                                    "home_team": p.home_team,
                                    "away_team": p.away_team,
                                    "match_time": str(p.match_time) if p.match_time else "",
                                }
                            )
                            match_dict.setdefault("odds", raw_data.get("odds", {}))
                            match_dict.setdefault("asian_odds", raw_data.get("asian_odds", {}))
                            match_dict.setdefault("recent_form", raw_data.get("recent_form", {}))
                            match_dict.setdefault("h2h_summary", raw_data.get("h2h_summary", "暂无"))
                            match_dict.setdefault("advanced_stats", raw_data.get("advanced_stats", {}))
                            if leisu:
                                inject_leisu_data(match_dict, leisu)

                            pred_text, _ = predictor.predict(
                                match_dict,
                                period="repredicted",
                                total_matches_count=len(candidates),
                            )
                            if pred_text and "预测失败" not in pred_text:
                                try:
                                    predicted_result = Database.extract_prediction_recommendation(pred_text)
                                    repredicted_record = db.session.query(MatchPrediction).filter(
                                        MatchPrediction.fixture_id == p.fixture_id,
                                        MatchPrediction.prediction_period == "repredicted",
                                    ).first()
                                    if not repredicted_record:
                                        repredicted_record = MatchPrediction(
                                            fixture_id=p.fixture_id,
                                            match_num=p.match_num,
                                            league=p.league,
                                            home_team=p.home_team,
                                            away_team=p.away_team,
                                            match_time=p.match_time,
                                            prediction_period="repredicted",
                                            raw_data=match_dict,
                                        )
                                        db.session.add(repredicted_record)
                                    repredicted_record.raw_data = match_dict
                                    repredicted_record.prediction_text = pred_text
                                    repredicted_record.predicted_result = predicted_result
                                    repredicted_record.actual_score = p.actual_score
                                    repredicted_record.actual_bqc = getattr(p, "actual_bqc", None)
                                    repredicted_record.actual_result = getattr(p, "actual_result", None)
                                    repredicted_record.htft_prediction_text = getattr(p, "htft_prediction_text", None)
                                    p.raw_data = match_dict
                                    db.session.commit()
                                    success_count += 1
                                except Exception as e:
                                    db.session.rollback()
                                    fail_count += 1
                                    st.warning(f"{p.match_num} 保存失败: {e}")
                            else:
                                fail_count += 1
                                st.warning(f"{p.match_num} 预测失败: {pred_text}")
                        except Exception as e:
                            fail_count += 1
                            st.warning(f"{p.match_num} 预测异常: {e}")
                        progress_bar.progress((i + 1) / len(candidates))

                    if leisu:
                        try:
                            leisu.close()
                        except Exception:
                            pass
                    progress_bar.empty()
                    if success_count > 0:
                        st.success(f"✅ 成功重新预测 {success_count}/{len(candidates)} 场比赛（period=repredicted）。")
                        if auto_update_review:
                            st.session_state["pm_auto_review_target_date"] = target_date_str
                        st.rerun()
                    if fail_count > 0:
                        st.error(f"❌ {fail_count} 场预测失败")
        
        # 3. AI 深度复盘
        st.divider()
        
        tab_full, tab_htft = st.tabs(["⚽ 全场预测深度复盘", "🌗 半全场(平胜/平负)专项复盘"])
        
        daily_review = db.get_daily_review(target_date_str)
        
        with tab_full:
            st.subheader("🧠 全场预测复盘与洞察")
            
            # 初始化 session_state 存储准确率报告
            if "acc_report" not in st.session_state:
                st.session_state.acc_report = None
            
            # 优先展示已持久化的复盘报告
            if daily_review and daily_review.review_content:
                with st.expander("� 查看复盘报告", expanded=True):
                    st.markdown(daily_review.review_content)
            else:
                st.info("该日尚无复盘报告，请点击下方按钮生成。")

            structured_entries = []
            for draft in get_pending_rule_drafts():
                if draft.get("source_date") != target_date_str:
                    continue
                case_id = draft.get("case_id") or "|".join(draft.get("source_matches") or [])
                if not case_id:
                    continue
                structured_entries.append({
                    "case_id": case_id,
                    "match_label": "、".join(draft.get("source_matches") or []) or "未知来源",
                    "title": draft.get("title", "未命名草稿"),
                    "disposition": draft.get("disposition", "未分类"),
                    "based_on_rule_id": draft.get("based_on_rule_id", ""),
                    "target_scope": draft.get("target_scope", "unknown"),
                    "market_review_complete": draft.get("market_review_complete", True),
                    "trigger_condition_nl": draft.get("trigger_condition_nl", "未提供"),
                    "is_executable": draft.get("is_executable", True),
                    "completeness_gaps": draft.get("completeness_gaps") or [],
                })

            if structured_entries:
                st.markdown("### 🧭 逐场规则修正入口")
                st.caption("先按比赛和处置类型进入，再决定是修旧规则还是新增规则。")
                for idx, entry in enumerate(structured_entries):
                    cols = st.columns([2.5, 1.2, 1.4, 1.2])
                    cols[0].write(f"**{entry['match_label']}**")
                    cols[1].write(f"`{entry['disposition']}`")
                    cols[2].write(f"`{entry['target_scope']}`")
                    entry_url = build_rule_manager_url(
                        current_auth_token,
                        focus_case=entry["case_id"],
                        focus_rule_id=entry["based_on_rule_id"],
                        focus_scope=entry["target_scope"],
                        focus_action=entry["disposition"],
                    )
                    cols[3].markdown(
                        f'<a href="{entry_url}" target="_blank" rel="noopener noreferrer">新页签处理</a>',
                        unsafe_allow_html=True,
                    )
                    if entry["based_on_rule_id"]:
                        st.write(f"关联旧规则：`{entry['based_on_rule_id']}`")
                    st.write(f"触发条件摘要：{entry['trigger_condition_nl']}")
                    if not entry["is_executable"]:
                        st.error(f"该场草稿尚不可采纳，缺少字段：{'、'.join(entry['completeness_gaps']) or 'unknown'}")
                    if entry["market_review_complete"] is False:
                        st.warning("该入口对应的盘口复盘仍不完整，建议先补盘口链路再下规则结论。")

            pending_rule_drafts = [
                draft for draft in get_pending_rule_drafts()
                if draft.get("source_date") == target_date_str
            ]
            if pending_rule_drafts:
                st.markdown("### 📝 候选规则草稿")
                st.caption("以下草稿来自当前日期复盘结果，可前往规则管理页审核并采纳。")
                for idx, draft in enumerate(pending_rule_drafts[:10]):
                    source_matches = "、".join(draft.get("source_matches") or []) or "未知来源"
                    with st.expander(f"{draft.get('title', '未命名草稿')} [{draft.get('target_scope', 'unknown')}]"):
                        st.write(f"问题类型：{draft.get('problem_type', '未标注')}")
                        st.write(f"来源比赛：{source_matches}")
                        disposition = draft.get("disposition", "未分类")
                        st.write(f"处置分类：{disposition}")
                        if draft.get("based_on_rule_id"):
                            st.write(f"基于旧规则：`{draft.get('based_on_rule_id')}`")
                        market_review_complete = draft.get("market_review_complete")
                        if market_review_complete is False:
                            st.warning("该草稿对应场次的盘口复盘仍不完整，请先补齐盘口链路再决定是否采纳。")
                        if not draft.get("is_executable", True):
                            st.error(f"该草稿尚不可采纳，缺少字段：{'、'.join(draft.get('completeness_gaps') or []) or 'unknown'}")
                        st.write(f"触发条件描述：{draft.get('trigger_condition_nl', '未提供')}")
                        st.write(f"建议条件：`{draft.get('suggested_condition', 'False')}`")
                        st.write(f"建议动作：`{draft.get('suggested_action', '')}`")
                        if draft.get("rule_id"):
                            st.write(f"候选规则ID：`{draft.get('rule_id')}`")
                        if draft.get("rule_name"):
                            st.write(f"规则名称：`{draft.get('rule_name')}`")
                        if draft.get("scenario_key"):
                            st.write(f"盘口剧本Key：`{draft.get('scenario_key')}`")
                        if draft.get("scenario_parts"):
                            st.write(f"盘口剧本拆分：`{' | '.join(draft.get('scenario_parts') or [])}`")
                        if draft.get("target_scope") == "micro_signal":
                            st.write(f"警告话术模板：`{draft.get('warning_message_template', '')}`")
                            st.write(f"预测偏向：`{draft.get('prediction_bias', '')}`")
                            st.write(f"作用类型：`{draft.get('effect_type', '')}`")
                        elif draft.get("target_scope") in {"arbitration_guard", "warning"}:
                            st.write(f"动作类型：`{draft.get('action_type', '')}`")
                            st.write(f"动作参数：`{draft.get('action_payload', {})}`")
                            st.write(f"解释模板：`{draft.get('explanation_template', '')}`")
                        draft_case_id = draft.get("case_id") or "|".join(draft.get("source_matches") or [])
                        target_scope = draft.get("target_scope", "")
                        shortcut_cols = st.columns(3)
                        repair_url = build_rule_manager_url(
                            current_auth_token,
                            focus_case=draft_case_id,
                            focus_rule_id=draft.get("based_on_rule_id", ""),
                            focus_scope=target_scope,
                            focus_action="optimize_existing",
                        )
                        shortcut_cols[0].markdown(
                            f'<a href="{repair_url}" target="_blank" rel="noopener noreferrer">修旧规则</a>',
                            unsafe_allow_html=True,
                        )
                        add_url = build_rule_manager_url(
                            current_auth_token,
                            focus_case=draft_case_id,
                            focus_rule_id=draft.get("based_on_rule_id", ""),
                            focus_scope=target_scope,
                            focus_action="add_new_rule",
                        )
                        shortcut_cols[1].markdown(
                            f'<a href="{add_url}" target="_blank" rel="noopener noreferrer">新增规则</a>',
                            unsafe_allow_html=True,
                        )
                        shortcut_cols[2].markdown(f"`{target_scope or 'unknown'}`")
                rule_manager_url = build_rule_manager_url(current_auth_token)
                st.markdown(
                    f'<a href="{rule_manager_url}" target="_blank" rel="noopener noreferrer">⚙️ 在新页签打开规则页审核这些草稿</a>',
                    unsafe_allow_html=True,
                )
            
            # LLM洞察按钮（先计算准确率，再让AI做洞察）
            if st.session_state.get("role") == "admin":
                st.divider()
                if st.session_state.get("pm_auto_review_target_date") == target_date_str:
                    st.session_state["pm_auto_review_target_date"] = None
                    import importlib, scripts.run_post_mortem
                    importlib.reload(scripts.run_post_mortem)
                    from scripts.run_post_mortem import compute_accuracy_report
                    with st.spinner("正在程序化计算准确率..."):
                        st.session_state.acc_report = compute_accuracy_report(target_date_str)
                    acc_report = st.session_state.acc_report
                    if acc_report and acc_report["overall"]["total"] > 0:
                        with st.spinner("AI正在基于准确率数据进行分析..."):
                            predictor = LLMPredictor()
                            review_text, rule_drafts, _case_mappings = predictor.generate_post_mortem(
                                target_date_str,
                                acc_report,
                                return_rule_drafts=True,
                            )
                            for draft in rule_drafts:
                                draft.setdefault("source_date", target_date_str)
                            replace_pending_rule_drafts_for_date(target_date_str, drafts=rule_drafts)
                            if db.save_daily_review(target_date_str, review_content=review_text):
                                st.success("复盘报告已生成！")
                                st.rerun()
                            else:
                                st.error("保存失败")
                    else:
                        st.error("暂无准确率数据，请先确保该日期有已完成比赛。")
                        st.stop()

                if st.button("🤖 生成/更新复盘报告", key="btn_full_review",
                           help="程序化计算准确率后，由AI基于数据做洞察分析"):
                    import importlib, scripts.run_post_mortem
                    importlib.reload(scripts.run_post_mortem)
                    from scripts.run_post_mortem import compute_accuracy_report
                    with st.spinner("正在程序化计算准确率..."):
                        st.session_state.acc_report = compute_accuracy_report(target_date_str)
                    
                    acc_report = st.session_state.acc_report
                    if acc_report and acc_report["overall"]["total"] > 0:
                        batch_label = acc_report.get("batch_label", target_date_str)
                        st.success(f"准确率计算完成：窗口 {batch_label}，共 {acc_report['overall']['total']} 场")
                        with st.spinner("AI正在基于准确率数据进行分析..."):
                            predictor = LLMPredictor()
                            review_text, rule_drafts, _case_mappings = predictor.generate_post_mortem(
                                target_date_str,
                                acc_report,
                                return_rule_drafts=True,
                            )
                            for draft in rule_drafts:
                                draft.setdefault("source_date", target_date_str)
                            replace_pending_rule_drafts_for_date(target_date_str, drafts=rule_drafts)
                            if db.save_daily_review(target_date_str, review_content=review_text):
                                st.success("复盘报告已生成！")
                                st.rerun()
                            else:
                                st.error("保存失败")
                    else:
                        st.error("暂无准确率数据，请先确保该日期有已完成比赛。")

        with tab_htft:
            st.subheader("🤖 AI 半全场(平胜/平负)专项复盘")
            if daily_review and daily_review.htft_review_content:
                st.success("已找到持久化的半全场复盘报告：")
                st.markdown(daily_review.htft_review_content)
            else:
                st.info("该日尚无持久化的 AI 半全场专项复盘报告。")
                
            if st.session_state.get("role") == "admin":
                if st.button("🧠 一键生成/更新半全场专项复盘报告", key="btn_htft_review"):
                    with st.spinner("AI 正在针对半全场（平胜/平负）剧本偏差进行深度剖析..."):
                        match_results_for_llm = []
                        for row in table_data:
                            match_results_for_llm.append({
                                "match_num": row["编号"],
                                "home": row["主队"],
                                "away": row["客队"],
                                "htft_prediction": row["_htft_rec"],
                                "actual_score": row["实际比分"],
                                "actual_bqc": row["_actual_bqc_cn"]
                            })
                            
                        from src.llm.htft_predictor import HTFTPredictor
                        htft_predictor = HTFTPredictor()
                        htft_review_text = htft_predictor.generate_post_mortem(target_date_str, match_results_for_llm)
                        
                        if db.save_daily_review(target_date_str, review_content=None, htft_review_content=htft_review_text):
                            st.success("半全场复盘报告生成并保存成功！")
                            st.rerun()
                        else:
                            st.error("保存半全场复盘报告失败。")

    db.close()

if __name__ == "__main__":
    main()
