# tgtrade_loop.ps1 — pętla restart Claude + Telegram bridge
# Uruchamiany przez funkcję tgtrade() z profilu PowerShell

$env:SSL_CERT_FILE = "C:\Users\krypt\.claude\windows-ca-bundle.pem"
$env:NODE_EXTRA_CA_CERTS = "C:\Users\krypt\.claude\windows-ca-bundle.pem"
$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"

# Znajdź najnowszego claude.exe z instalacji Claude Desktop (nie npm — npm claude.exe jest nieaktywny)
$claudeDir = "C:\Users\krypt\AppData\Roaming\Claude\claude-code"
$claude = Get-ChildItem $claudeDir -Filter "claude.exe" -Recurse -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName

if (-not $claude) {
    Write-Host "[ERROR] Nie znaleziono claude.exe w $claudeDir" -ForegroundColor Red
    Write-Host "Zainstaluj Claude Desktop z claude.ai/download" -ForegroundColor Yellow
    Read-Host "Nacisnij Enter aby wyjsc"
    exit 1
}

$host.UI.RawUI.WindowTitle = "tgtrade — Telegram Bridge"
Set-Location C:\Users\krypt\trading-ai

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  tgtrade — Telegram Bridge (auto-restart)  " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Claude: $claude" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] Claude + Telegram startuje. Profilaktyczny restart ~23:58." -ForegroundColor Green
    & $claude --dangerously-skip-permissions --channels plugin:telegram@claude-plugins-official
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host ""
    Write-Host "[$ts] Sesja zakonczona/zrestartowana. Wstaje za 5s (Ctrl+C = stop)." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
