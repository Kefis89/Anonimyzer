@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Окружение не установлено.
    echo Сначала запустите install.bat
    echo.
    pause
    exit /b 1
)

REM Показать API-ключ из .env (нужен для заголовка X-API-Key)
set "APIKEY="
if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (".env") do if "%%A"=="ANONYMIZER_API_KEY" set "APIKEY=%%B"

echo ============================================
echo   Anonymizer — HTTP API
echo   Адрес:  http://127.0.0.1:8077
if defined APIKEY echo   Ключ:   %APIKEY%
echo   Проверка: http://127.0.0.1:8077/health
echo   Остановить: Ctrl+C или закрыть это окно
echo ============================================
echo.

".venv\Scripts\python.exe" run.py

echo.
echo Сервер остановлен.
pause
 