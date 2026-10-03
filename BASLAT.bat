@echo off
cd /d "%~dp0"
if exist "dist\CiftlikTakip.exe" (
    "dist\CiftlikTakip.exe"
    exit /b
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" desktop_launcher.py
    exit /b
)
echo Calistirici bulunamadi. README.md dosyasindaki kurulum adimlarini uygulayin.
pause
