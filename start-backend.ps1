$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = "CargoAI Backend - port 8000"
$env:CARGOAI_FRONTEND_ORIGIN = "http://localhost:3000"
$env:DATABASE_URL = "sqlite:///./cargoai-demo.db"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Demo database migration failed" }
$demoTenant = & "$PSScriptRoot\.venv\Scripts\python.exe" -c "from database.session import session_scope; from database.seed import seed_demo; exec('with session_scope() as session:\n    result = seed_demo(session)'); print(result['tenant_id'])"
if ($LASTEXITCODE -ne 0) { throw "Demo database seed failed" }
$env:CARGOAI_DEMO_TENANT_ID = "$demoTenant".Trim()
$env:CARGOAI_LOCAL_DEMO = "1"
Write-Host "Local demo pricing enabled using synthetic October 2026 rates."
Write-Host "Backend: http://127.0.0.1:8000 | Frontend: http://localhost:3000"
Write-Host "Extraction errors and tracebacks appear in this window. Ctrl+C stops the backend."
$ErrorActionPreference = "Continue"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers --log-level debug --access-log 2>&1 | Tee-Object -FilePath "$PSScriptRoot\backend.log"
