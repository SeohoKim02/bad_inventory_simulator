@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ========================================
echo   VARO GitHub 반자동 코드 저장
echo ========================================
echo.

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [오류] 현재 폴더가 Git 저장소가 아닙니다.
    echo 프로젝트 폴더에서 이 파일을 실행해야 합니다.
    pause
    exit /b 1
)

if not exist ".gitignore" (
    type nul > ".gitignore"
)

findstr /x /c:"__pycache__/" ".gitignore" >nul 2>nul || echo __pycache__/>> ".gitignore"
findstr /x /c:"*.pyc" ".gitignore" >nul 2>nul || echo *.pyc>> ".gitignore"
findstr /x /c:".streamlit/secrets.toml" ".gitignore" >nul 2>nul || echo .streamlit/secrets.toml>> ".gitignore"
findstr /x /c:"dqn_artifacts/" ".gitignore" >nul 2>nul || echo dqn_artifacts/>> ".gitignore"

echo [1/4] 저장할 코드 파일 추가 중...

for %%F in (
    app.py
    dashboard_pages.py
    kakao_map_viewer.py
    cutline_analyzer.py
    transfer_path_analyzer.py
    dqn_agent.py
    github_dqn_uploader.py
    rl_data_logger.py
    rl_policy_helper.py
    calculator.py
    discount_analyzer.py
    excel_loader.py
    route_analyzer.py
    time_window_analyzer.py
    promotion_analyzer.py
    network_path_analyzer.py
    final_summary.py
    heuristic_optimizer.py
    requirements.txt
    .gitignore
) do (
    if exist "%%F" (
        git add "%%F"
        echo   추가: %%F
    )
)

echo.
echo [2/4] 현재 변경 사항:
git status --short

echo.
set /p CONFIRM=이대로 GitHub에 저장할까요? (Y/N): 

if /I not "%CONFIRM%"=="Y" (
    echo 취소했습니다.
    pause
    exit /b 0
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i

echo.
echo [3/4] 커밋 생성 중...
git commit -m "Update VARO project %TS%"

if errorlevel 1 (
    echo.
    echo 커밋할 변경 사항이 없거나 커밋 중 문제가 발생했습니다.
    echo 아래 상태를 확인하세요.
    git status
    pause
    exit /b 0
)

echo.
echo [4/4] GitHub에 업로드 중...
git push origin main

if errorlevel 1 (
    echo.
    echo [오류] GitHub 업로드 실패.
    echo 인터넷 연결, GitHub 로그인, 저장소 주소를 확인하세요.
    pause
    exit /b 1
)

echo.
echo 완료! GitHub에 코드가 저장되었습니다.
pause
