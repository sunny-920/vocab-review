@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

echo [1/4] 建立虛擬環境 .venv（只在這個資料夾裡，不影響系統 Python）
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || goto :fail
)

echo [2/4] 安裝 Python 套件
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

echo [3/4] 離線字典
if exist "data\ecdict_lite.db" (
    echo     已經有字典，略過
) else (
    ".venv\Scripts\python.exe" -I tools\setup_dict.py || goto :fail
)

echo [4/4] 自然語音模型（約 340MB，下載失敗也能用，會改用瀏覽器發音）
".venv\Scripts\python.exe" -I tools\setup_tts.py || echo     下載失敗，之後可以再執行一次安裝.bat

echo.
echo 安裝完成！之後雙擊「啟動.bat」就能使用。
pause
exit /b 0

:fail
echo.
echo 安裝失敗，請把上面的訊息截圖給 Claude 看。
pause
exit /b 1
