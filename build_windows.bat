@echo off
setlocal

cd /d "%~dp0"

if not exist logs mkdir logs

pyinstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name CleanDesk ^
  --icon assets\cleandesk.ico ^
  --add-data "assets\cleandesk.ico;assets" ^
  --distpath dist ^
  --workpath build ^
  main.py

echo.
echo Build finished: dist\CleanDesk\CleanDesk.exe
endlocal
