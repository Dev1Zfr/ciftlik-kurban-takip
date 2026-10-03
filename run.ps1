$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Önce README.md içindeki yerel kurulum adımlarını uygulayın.'
}

Set-Location -LiteralPath $projectRoot
& $python -m flask --app app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload
