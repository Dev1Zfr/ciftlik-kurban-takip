$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Yerel .venv bulunamadı. Önce README.md içindeki kurulum adımlarını uygulayın.'
}

Set-Location -LiteralPath $projectRoot
& $python -m pip install --disable-pip-version-check -r requirements-build.txt
& $python -m PyInstaller --noconfirm --clean --onefile --name CiftlikTakip --add-data "templates;templates" desktop_launcher.py
Write-Host "Hazır: $projectRoot\dist\CiftlikTakip.exe"
