@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Anonymizer — установка (запустить один раз)
echo ============================================
echo.

REM --- 1. Найти Python ---
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [ОШИБКА] Python не найден.
    echo Установите Python 3.10+ с https://www.python.org/downloads/
    echo При установке ОБЯЗАТЕЛЬНО отметьте галочку "Add Python to PATH".
    goto :error
)
echo Python найден:
%PY% --version
echo.

REM --- 2. Виртуальное окружение ---
if exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение .venv уже есть — пропускаю создание.
) else (
    echo Создаю виртуальное окружение .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :error
)
set "VPY=.venv\Scripts\python.exe"
echo.

REM --- 3. Зависимости ---
echo Обновляю pip ...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :error
echo.

echo Устанавливаю зависимости из requirements.txt ...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.

echo Скачиваю модель spaCy ru_core_news_lg (~0.5 ГБ — это может быть долго) ...
"%VPY%" -m spacy download ru_core_news_lg
if errorlevel 1 goto :error
echo.

echo Фиксирую setuptools^<81 (иначе детектор Natasha молча отключится) ...
"%VPY%" -m pip install "setuptools<81"
if errorlevel 1 goto :error
echo.

REM --- 4. Файл .env с API-ключом ---
if exist ".env" (
    echo Файл .env уже существует — оставляю как есть.
) else (
    echo Создаю .env и генерирую надёжный API-ключ ...
    for /f "delims=" %%K in ('%VPY% -c "import secrets;print(secrets.token_hex(32))"') do set "APIKEY=%%K"
    > .env  echo ANONYMIZER_API_KEY=!APIKEY!
    >> .env echo ANONYMIZER_HOST=127.0.0.1
    >> .env echo ANONYMIZER_PORT=8077
    echo.
    echo Ваш API-ключ сохранён в файле .env. Он нужен для заголовка X-API-Key:
    echo     !APIKEY!
)
echo.

echo ============================================
echo   Установка завершена.
echo   Теперь запускайте сервер файлом  start.bat
echo ============================================
echo.
pause
exit /b 0
 
:error
echo.
echo [ОШИБКА] Установка прервана — смотрите сообщение выше.
echo.
pause
exit /b 1
