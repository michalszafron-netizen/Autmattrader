$py   = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$base = "C:\Users\markowyy\trading-ai\scripts"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== Trading AI Daemons ===" -ForegroundColor Cyan

# Volume Scanner — w osobnym oknie
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$py' '$base\volume_scanner.py' --daemon --interval 3600 --threshold 3"
)

# Smart Money — w osobnym oknie
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$py' '$base\smart_money_tracker.py' --daemon --interval 3600"
)

# Listings — w osobnym oknie
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$py' '$base\listings_scanner.py' --daemon --interval 21600"
)

# TV Webhook — TradingView alert receiver (port 5005)
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$py' '$base\tv_webhook.py' --port 5005"
)

# ── Insider Tracker — Windows Task Scheduler (nie daemon, cron-style) ─────────
# Eddie   — daily 06:00   (SEC Form 4 insider buys)
# Maggie  — Sunday 19:00  (13F institutional filings)
# Frank   — Monday 08:00  (Fed speech sentiment)

$insiderScript = "$base\insider_tracker.py"

$taskFolder = "\InsiderRoutines"
$taskService = New-Object -ComObject Schedule.Service
$taskService.Connect()
try { $taskService.GetFolder($taskFolder) } catch {
    $rootFolder = $taskService.GetFolder("\")
    $rootFolder.CreateFolder($taskFolder) | Out-Null
}

function Register-InsiderTask($name, $scout, $trigger) {
    $taskName = "Insider-$name"
    $sched = New-Object -ComObject Schedule.Service
    $sched.Connect()
    $folder = $sched.GetFolder($taskFolder)
    try { $folder.DeleteTask($taskName, 0) } catch {}
    Register-ScheduledTask `
        -TaskName $taskName -TaskPath "$taskFolder\" `
        -Action (New-ScheduledTaskAction -Execute $py -Argument "`"$insiderScript`" $scout" -WorkingDirectory "C:\Users\markowyy\trading-ai") `
        -Trigger $trigger `
        -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)) `
        -Description "Insider Tracker · $name" | Out-Null
    Write-Host "  OK  \InsiderRoutines\Insider-$name" -ForegroundColor Green
}

Write-Host "`nRegistering Insider Tracker scheduled tasks..." -ForegroundColor Cyan
Register-InsiderTask "Eddie"  "form4"         (New-ScheduledTaskTrigger -Daily -At 06:00)
Register-InsiderTask "Maggie" "institutional" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 19:00)
Register-InsiderTask "Frank"  "fed"           (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 08:00)

Write-Host "3 okna otwarte + 3 Insider tasks zaplanowane." -ForegroundColor Green
