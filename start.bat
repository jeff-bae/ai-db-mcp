@echo off
chcp 65001 > nul
echo AI-MCP-DB 시작 중...
cd /d "%~dp0"
python app.py
pause
