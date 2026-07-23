@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

for /f "delims=" %%V in ('python -c "from version import APP_VERSION; print(APP_VERSION)" 2^>nul') do set "CLEANDESK_VERSION=%%V"
if not defined CLEANDESK_VERSION (
  echo [错误] 无法从 version.py 读取版本号。
  exit /b 1
)

if not exist "dist\CleanDesk\CleanDesk.exe" (
  echo [错误] 未找到 dist\CleanDesk\CleanDesk.exe。
  echo 请先运行 build_windows.bat 生成完整 Windows 程序目录。
  exit /b 1
)

set "ISCC_EXE="
if defined ISCC_EXE_OVERRIDE if exist "%ISCC_EXE_OVERRIDE%" set "ISCC_EXE=%ISCC_EXE_OVERRIDE%"

if not defined ISCC_EXE (
  for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC_EXE set "ISCC_EXE=%%I"
)

if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC_EXE (
  set "INNO_ICON="
  for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Classes\InnoSetupScriptFile\DefaultIcon" /ve 2^>nul ^| find /i "REG_SZ"') do set "INNO_ICON=%%B"
  if defined INNO_ICON (
    set "INNO_ICON=!INNO_ICON:,1=!"
    for %%I in ("!INNO_ICON!") do if exist "%%~dpIISCC.exe" set "ISCC_EXE=%%~dpIISCC.exe"
  )
)

if not defined ISCC_EXE (
  echo [错误] 未找到 Inno Setup 命令行编译器 ISCC.exe。
  echo 请先安装 Inno Setup，或设置 ISCC_EXE_OVERRIDE 指向 ISCC.exe。
  exit /b 1
)

if not exist "releases\%CLEANDESK_VERSION%" mkdir "releases\%CLEANDESK_VERSION%"
if errorlevel 1 exit /b 1

echo 正在使用：%ISCC_EXE%
echo 正在构建 CleanDesk %CLEANDESK_VERSION% 安装程序...
"%ISCC_EXE%" "installer\CleanDesk.iss"
if errorlevel 1 (
  echo [错误] Inno Setup 编译失败。
  exit /b 1
)

set "SETUP_OUTPUT=releases\%CLEANDESK_VERSION%\CleanDesk_%CLEANDESK_VERSION%_Setup.exe"
if not exist "%SETUP_OUTPUT%" (
  echo [错误] 编译结束，但未找到：%SETUP_OUTPUT%
  exit /b 1
)

echo.
echo 安装程序已生成：%SETUP_OUTPUT%
exit /b 0
