@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%cd%\logs\build_windows.log"

echo [INFO] Windows build started > "%LOG_FILE%"
echo [INFO] Working directory: %cd% >> "%LOG_FILE%"

where py >nul 2>nul
if %errorlevel% neq 0 (
  where python >nul 2>nul
  if %errorlevel% neq 0 (
    echo [ERROR] Python not found >> "%LOG_FILE%"
    echo.
    echo 没有找到 Python。
    echo 请先安装 Python 3.11 或 3.12，并勾选 Add python.exe to PATH。
    echo 日志文件: %LOG_FILE%
    pause
    exit /b 1
  )
  set "PY_CMD=python"
) else (
  set "PY_CMD=py"
)

echo [INFO] Using interpreter: %PY_CMD% >> "%LOG_FILE%"

echo.
echo 正在安装或检查打包依赖...
%PY_CMD% -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Failed to upgrade pip >> "%LOG_FILE%"
  echo 依赖准备失败，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

%PY_CMD% -m pip install pyinstaller pillow >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Failed to install dependencies >> "%LOG_FILE%"
  echo 安装依赖失败，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

echo.
echo 开始打包 Windows 管理器...
%PY_CMD% tools\build_windows_exe.py >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Build failed >> "%LOG_FILE%"
  echo 打包失败，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

if exist "dist_windows\指纹浏览器-Windows" (
  echo [INFO] Build finished: dist_windows\指纹浏览器-Windows >> "%LOG_FILE%"
  echo.
  echo 打包完成，正在打开输出目录...
  start "" "dist_windows\指纹浏览器-Windows"
) else (
  echo [WARN] Build command finished but output folder was not found >> "%LOG_FILE%"
  echo 打包命令执行完了，但没有找到输出目录，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

echo.
echo 已完成。日志文件: %LOG_FILE%
pause
