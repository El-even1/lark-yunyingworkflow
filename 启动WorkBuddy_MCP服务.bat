@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   爆款话题挖掘 · WorkBuddy 局域网共享 MCP 服务
echo   端口: 8502  (Streamable HTTP: /mcp)
echo ============================================================
python bkworkflow\mcp_server.py --http --host 0.0.0.0 --port 8502
pause
