Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Starting Streamlit server: http://127.0.0.1:8501"
Write-Host "Press Ctrl+C to stop."

$env:STREAMLIT_CONFIG_DIR = Join-Path $PSScriptRoot '.streamlit'

& .\venv\Scripts\streamlit run src\app.py --server.port 8501 --server.address 127.0.0.1
