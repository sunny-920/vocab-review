@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
title 單字複習（關閉這個視窗就會結束程式）

if not exist ".venv\Scripts\python.exe" (
    echo 還沒安裝，請先雙擊「安裝.bat」。
    pause
    exit /b 1
)

rem 確保 Ollama 有在執行（沒在執行時會自動啟動）
ollama list >nul 2>&1

".venv\Scripts\python.exe" -m app
if errorlevel 1 pause
