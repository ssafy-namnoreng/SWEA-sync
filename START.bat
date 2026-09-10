@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem 파이썬 실행기 찾기 (python 이 PATH 에 없고 py 런처만 있는 PC 가 흔함)
set PY=
where python >nul 2>&1 && set PY=python
if not defined PY (where py >nul 2>&1 && set PY=py)
if not defined PY (
  echo.
  echo   [실패] 파이썬을 찾지 못했습니다.
  echo   python.org 에서 Python 을 설치하되,
  echo   설치 화면에서 "Add Python to PATH" 를 꼭 체크해주세요.
  echo.
  pause
  exit /b 1
)

%PY% swea_sync.py %*
set RC=%errorlevel%
if not "%RC%"=="0" (
  echo.
  echo   [실패] 위 메시지를 확인해주세요.
  echo.
  pause
)
