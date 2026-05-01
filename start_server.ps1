Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "========================================================"
Write-Host "         Football & Basketball Prediction System        " -ForegroundColor Cyan
Write-Host "========================================================"
Write-Host ""
Write-Host "正在启动服务..."
Write-Host "按 Ctrl+C 可停止服务" -ForegroundColor Yellow
Write-Host ""

# 设置 Streamlit 配置目录环境变量，避免使用用户全局配置
$env:STREAMLIT_CONFIG_DIR = Join-Path $PSScriptRoot ".streamlit"

# 使用虚拟环境中的 streamlit 启动 app.py
& .\venv\Scripts\streamlit run src\app.py --server.port 8501 --server.address 127.0.0.1
