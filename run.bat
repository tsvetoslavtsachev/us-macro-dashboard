@echo off
REM ============================================================
REM us-macro-dashboard — Main launcher
REM Double-click този файл и ползвай менюто.
REM ============================================================

REM UTF-8 за кирилица в терминала
chcp 65001 >nul

REM Отива в директорията на .bat файла (работи независимо откъде е извикан)
cd /d "%~dp0"

:MENU
cls
echo ============================================================
echo   us-macro-dashboard
echo ============================================================
echo.
echo   1. Data status         (бърза проверка кои серии са свежи)
echo   2. Briefing - бърз      (без historical analogs)
echo   3. Briefing - пълен     (analogs + journal)  ^<-- основен workflow
echo   4. Refresh данни...     (отделно меню — без briefing)
echo   5. Rebuild journal index
echo   6. Run tests
echo   7. Open output folder
echo   8. Git status           (какво си променил след последния commit)
echo.
echo   0. Exit
echo.
set /p choice="Избор: "

if "%choice%"=="1" goto STATUS
if "%choice%"=="2" goto BRIEF_QUICK
if "%choice%"=="3" goto BRIEF_FULL
if "%choice%"=="4" goto REFRESH_MENU
if "%choice%"=="5" goto JOURNAL_IDX
if "%choice%"=="6" goto TESTS
if "%choice%"=="7" goto OPEN_OUTPUT
if "%choice%"=="8" goto GIT_STATUS
if "%choice%"=="0" exit /b 0
goto MENU

:STATUS
echo.
echo --- Running: python run.py --status
echo.
python run.py --status
echo.
pause
goto MENU

:BRIEF_QUICK
echo.
echo --- Running: python run.py --briefing --with-journal
echo.
python run.py --briefing --with-journal
echo.
pause
goto MENU

:BRIEF_FULL
echo.
echo --- Running: python run.py --briefing --with-analogs --with-journal
echo.
python run.py --briefing --with-analogs --with-journal
echo.
pause
goto MENU

:REFRESH_MENU
cls
echo ============================================================
echo   Refresh данни — избор
echo ============================================================
echo.
echo   1. Smart refresh           (само stale серии — бързо)
echo   2. Force refresh            (всички 69 серии re-fetch — бавно)
echo   3. Briefing - пълен + force refresh  (всичко наведнъж)
echo.
echo   0. Назад към главното меню
echo.
set /p rchoice="Избор: "

if "%rchoice%"=="1" goto REFRESH_SMART
if "%rchoice%"=="2" goto REFRESH_FORCE
if "%rchoice%"=="3" goto BRIEF_REFRESH_FULL
if "%rchoice%"=="0" goto MENU
goto REFRESH_MENU

:REFRESH_SMART
echo.
echo --- Running: python run.py --refresh-only
echo.
python run.py --refresh-only
echo.
pause
goto REFRESH_MENU

:REFRESH_FORCE
echo.
echo --- Running: python run.py --refresh-only --refresh
echo.
python run.py --refresh-only --refresh
echo.
pause
goto REFRESH_MENU

:BRIEF_REFRESH_FULL
echo.
echo --- Running: python run.py --briefing --refresh --with-analogs --with-journal
echo.
python run.py --briefing --refresh --with-analogs --with-journal
echo.
pause
goto MENU

:JOURNAL_IDX
echo.
echo --- Running: python -m scripts.build_journal_index
echo.
python -m scripts.build_journal_index
echo.
pause
goto MENU

:TESTS
echo.
echo --- Running: pytest tests/ -q
echo.
pytest tests/ -q
echo.
pause
goto MENU

:OPEN_OUTPUT
start "" "output"
goto MENU

:GIT_STATUS
echo.
git status
echo.
pause
goto MENU
