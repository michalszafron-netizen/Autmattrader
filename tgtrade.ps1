$claude = "C:\Users\markowyy\AppData\Roaming\Claude\claude-code\2.1.149\claude.exe"
if (-not (Test-Path $claude)) {
    $claude = Get-ChildItem "C:\Users\markowyy\AppData\Roaming\Claude\claude-code" -Filter "claude.exe" -Recurse |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
Write-Host "Trading AI Telegram Bridge: $claude" -ForegroundColor Cyan
Set-Location "C:\Users\markowyy\trading-ai"
& $claude --channels plugin:telegram@claude-plugins-official
