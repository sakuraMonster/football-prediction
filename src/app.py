import streamlit as st
import sys
import os
import hashlib
import json
import asyncio
from datetime import datetime

# 强制恢复 Windows 默认的 ProactorEventLoop，解决子进程 NotImplementedError
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import nest_asyncio
nest_asyncio.apply()

from dotenv import load_dotenv
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_base, "config", ".env"))

sys.path.insert(0, _base)

from src.logging_config import setup_logging
setup_logging()
from loguru import logger

from src.db.database import Database
from src.constants import AUTH_TOKEN_TTL

# 设置页面配置 (主入口文件必须包含)
st.set_page_config(
    page_title="泊松数据模型 - 登录",
    page_icon="⚽",
    layout="centered",
    initial_sidebar_state="collapsed", # 登录页隐藏侧边栏
)

# 隐藏 Streamlit 默认的侧边栏页面导航
hide_pages_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
    </style>
"""
st.markdown(hide_pages_style, unsafe_allow_html=True)

import base64
import time

def encode_auth_token(username):
    # 生成包含时间戳的 token：username|timestamp
    raw = f"{username}|{int(time.time())}"
    return base64.b64encode(raw.encode('utf-8')).decode('utf-8')

def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        username, timestamp = raw.split('|')
        return username, int(timestamp)
    except:
        return None, 0

# 尝试从 Query Params (URL 参数) 恢复登录状态 (带1小时有效期验证)
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
                st.session_state["auth_token"] = token
                st.switch_page("pages/1_Dashboard.py")
    except Exception as e:
        pass

# 初始化 Session State
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.session_state["auth_token"] = ""

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def check_login(username, password):
    db = Database()
    user = db.get_user(username)
    db.close()
    
    if not user:
        return False, "用户不存在", None
        
    if user.password_hash != hash_password(password):
        return False, "密码错误", None
        
    if datetime.now() > user.valid_until:
        return False, f"账号授权已于 {user.valid_until.strftime('%Y-%m-%d')} 到期，请联系管理员", None
        
    return True, user.role, user.valid_until

def main():
    if st.session_state["logged_in"]:
        # 如果已经登录，提示并提供跳转按钮
        st.success(f"欢迎回来，{st.session_state['username']}！")
        st.write("您已成功登录系统。")
        token = st.session_state.get("auth_token") or encode_auth_token(st.session_state["username"])
        st.session_state["auth_token"] = token
        # 注意 Streamlit 的路由规则，pages 目录下的文件会忽略前缀数字和下划线，"1_Dashboard.py" 的路由就是 "Dashboard"
        nav_url = f"/Dashboard?auth={token}"
        st.markdown(f'<a href="{nav_url}" target="_self"><button style="width:100%; padding:10px; background-color:#FF4B4B; color:white; border:none; border-radius:5px; cursor:pointer;">👉 进入赛事预测看板</button></a>', unsafe_allow_html=True)
        
        if st.button("退出登录"):
            st.session_state["logged_in"] = False
            st.session_state["username"] = ""
            st.session_state["role"] = ""
            st.session_state["auth_token"] = ""
            if "auth" in st.query_params:
                del st.query_params["auth"]
            st.rerun()
    else:
        st.title("🔒 欢迎登录 泊松数据模型系统")
        st.markdown("本系统为内部邀请制，请使用授权账号登录。")
        
        # 居中显示登录框
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                st.subheader("账号登录")
                username = st.text_input("用户名")
                password = st.text_input("密码", type="password")
                submitted = st.form_submit_button("登录", use_container_width=True)
                
                if submitted:
                    if not username or not password:
                        st.error("请输入账号和密码")
                    else:
                        result = check_login(username, password)
                        if result[0]:
                            st.session_state["logged_in"] = True
                            st.session_state["username"] = username
                            st.session_state["role"] = result[1]
                            st.session_state["valid_until"] = result[2]
                            
                            st.success("登录成功！请点击下方按钮进入系统...")
                            # 生成带有时间戳的加密 token
                            token = encode_auth_token(username)
                            st.session_state["auth_token"] = token
                            # 路由必须是 /Dashboard (Streamlit 会自动忽略文件名的数字前缀)
                            nav_url = f"/Dashboard?auth={token}"
                            st.markdown(f'<meta http-equiv="refresh" content="1;url={nav_url}">', unsafe_allow_html=True)
                            st.markdown(f'<a href="{nav_url}" target="_self"><button style="width:100%; padding:10px; background-color:#FF4B4B; color:white; border:none; border-radius:5px; cursor:pointer;">👉 点击这里进入看板</button></a>', unsafe_allow_html=True)
                        else:
                            st.error(result[1])

if __name__ == "__main__":
    main()
