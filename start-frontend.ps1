$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "frontend")
$Host.UI.RawUI.WindowTitle = "CargoAI Frontend - port 3000"
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --hostname 127.0.0.1
