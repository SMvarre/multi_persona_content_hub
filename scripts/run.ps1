# Start Content Hub API (port 8001 — avoid 8000 which may be another app)
Set-Location $PSScriptRoot\..

$port = 8001
$conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "Stopping process on port $port (PID $($conn.OwningProcess))..."
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "Starting Multi-Persona Content Hub on http://127.0.0.1:$port"
Write-Host "Open that URL in your browser. Indexed documents persist in data\chroma."
& .\.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port $port
