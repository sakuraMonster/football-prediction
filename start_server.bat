@echo off
echo ========================================================
echo          Football ^& Basketball Prediction System
echo ========================================================
echo.
echo 正在启动服务...
echo 请不要关闭此窗口！
echo.

set STREAMLIT_CONFIG_DIR=%~dp0.streamlit
.\venv\Scripts\streamlit run src\app.py --server.port 8501 --server.address 127.0.0.1
pause
