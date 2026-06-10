# Build docs/WEEKLY_REPORT.docx from docs/WEEKLY_REPORT.md (uses project venv)
Set-Location $PSScriptRoot\..

& .\.venv\Scripts\python.exe scripts\convert_report_to_docx.py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done. Open docs\WEEKLY_REPORT.docx in Word."
