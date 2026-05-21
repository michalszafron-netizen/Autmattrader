# keepalive.ps1 — prevents Windows from throttling/sleeping the tgtrade session
#
# Uses Windows SetThreadExecutionState API to tell the OS:
# "this process needs to stay active, do NOT throttle it"
# Runs silently in background alongside tgtrade.
#
# Interval: every 20 minutes sends a keepalive ping.

param(
    [int]$IntervalMinutes = 20,
    [string]$BotToken = "",
    [string]$ChatId = ""
)

# Load .env to get bot credentials if not passed as params
if (-not $BotToken) {
    $envFile = Join-Path $PSScriptRoot "..\\.env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^TELEGRAM_BOT_TOKEN=(.+)$") { $BotToken = $Matches[1].Trim() }
            if ($_ -match "^TELEGRAM_ALLOWED_USER_ID=(.+)$") { $ChatId = $Matches[1].Trim() }
        }
    }
}

# Windows API: prevent system sleep and background throttling
$code = @"
using System;
using System.Runtime.InteropServices;
public class PowerMgmt {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS       = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED  = 0x00000001;
    public const uint ES_DISPLAY_REQUIRED = 0x00000002;
}
"@

Add-Type -TypeDefinition $code -Language CSharp

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED — tells Windows: keep this thread's process running
[PowerMgmt]::SetThreadExecutionState(
    [PowerMgmt]::ES_CONTINUOUS -bor [PowerMgmt]::ES_SYSTEM_REQUIRED
) | Out-Null

Write-Host "[keepalive] Started. Interval: ${IntervalMinutes}min. Press Ctrl+C to stop."
Write-Host "[keepalive] Windows sleep prevention: ACTIVE"

$count = 0
while ($true) {
    Start-Sleep -Seconds ($IntervalMinutes * 60)
    $count++

    # Refresh the execution state (some Windows versions require periodic refresh)
    [PowerMgmt]::SetThreadExecutionState(
        [PowerMgmt]::ES_CONTINUOUS -bor [PowerMgmt]::ES_SYSTEM_REQUIRED
    ) | Out-Null

    $ts = Get-Date -Format "HH:mm"

    # Optional: send a silent Telegram API ping (getMe) to keep the connection warm
    # This does NOT send any message to the user — just keeps the HTTP connection alive
    if ($BotToken) {
        try {
            $null = Invoke-RestMethod -Uri "https://api.telegram.org/bot$BotToken/getMe" -TimeoutSec 10
            Write-Host "[keepalive] $ts ping #$count — OK"
        } catch {
            Write-Host "[keepalive] $ts ping #$count — warn: $($_.Exception.Message)"
        }
    } else {
        Write-Host "[keepalive] $ts heartbeat #$count"
    }
}
