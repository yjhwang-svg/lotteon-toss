# Register the Toss re-collection worker as a logon-triggered task.
# Run once on the PC that has Toss-logged-in Chrome + browser-harness:
#   powershell -ExecutionPolicy Bypass -File register_worker.ps1

$ErrorActionPreference = "Stop"

$TaskName = "TossWorker"
$PythonW  = "C:\Users\MADUP\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
$Script   = Join-Path $PSScriptRoot "toss_worker.py"
$WorkDir  = $PSScriptRoot

# Remove existing task if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task"
}

$action   = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Script`"" -WorkingDirectory $WorkDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Toss re-collection queue worker" -Force | Out-Null

Write-Host "[OK] Task '$TaskName' registered (auto-start at logon)"

schtasks /Run /TN $TaskName | Out-Null
Write-Host "[OK] Worker started now"
