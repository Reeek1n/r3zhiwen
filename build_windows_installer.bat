@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%cd%\logs\build_windows_installer.log"

echo [INFO] Windows installer build started > "%LOG_FILE%"
echo [INFO] Working directory: %cd% >> "%LOG_FILE%"

if not exist "dist_windows\指纹浏览器-Windows" (
  echo [WARN] App build output missing, running app build first >> "%LOG_FILE%"
  call build_windows.bat >> "%LOG_FILE%" 2>&1
  if %errorlevel% neq 0 (
    echo [ERROR] Failed to build app before installer >> "%LOG_FILE%"
    echo 程序本体打包失败，请查看日志: %LOG_FILE%
    pause
    exit /b 1
  )
)

set "ISCC_CMD="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_CMD=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_CMD=C:\Program Files\Inno Setup 6\ISCC.exe"

if "%ISCC_CMD%"=="" (
  echo [ERROR] Inno Setup not found >> "%LOG_FILE%"
  echo.
  echo 没有找到 Inno Setup 6。
  echo 请先安装 Inno Setup 6，再重新双击这个脚本。
  echo 日志文件: %LOG_FILE%
  pause
  exit /b 1
)

echo [INFO] Using Inno Setup: %ISCC_CMD% >> "%LOG_FILE%"

echo.
echo 开始生成安装包...
"%ISCC_CMD%" "windows_installer.iss" >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Installer build failed >> "%LOG_FILE%"
  echo 安装包打包失败，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

if exist "installer_dist\FingerprintBrowserWindowsSetup.exe" (
  echo [INFO] Installer build finished: installer_dist\FingerprintBrowserWindowsSetup.exe >> "%LOG_FILE%"
  echo.
  echo 安装包已生成，正在打开输出目录...
  start "" "installer_dist"
) else (
  echo [WARN] Installer build finished but setup exe was not found >> "%LOG_FILE%"
  echo 没找到安装包输出，请查看日志: %LOG_FILE%
  pause
  exit /b 1
)

echo.
echo 已完成。日志文件: %LOG_FILE%
pause
