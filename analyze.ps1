# Paste a YouTube link, get a sentiment report.
#   .\analyze.ps1 "https://www.youtube.com/watch?v=VIDEO_ID"
# First run creates .venv and installs everything (the ML model downloads once, ~1 GB).
# Extra flags pass straight through, e.g.  .\analyze.ps1 <url> --max-comments 2000 --no-open
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Url,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "First run: creating .venv and installing dependencies..." -ForegroundColor Cyan
    python -m venv .venv
    & .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    & .venv\Scripts\python.exe -m pip install --quiet -e ".[ml]"
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Put your YouTube Data API v3 key in it (YOUTUBE_API_KEY=...), then run again." -ForegroundColor Yellow
    notepad .env
    exit 1
}
& .venv\Scripts\python.exe -m ytpulse analyze $Url @Rest
exit $LASTEXITCODE
