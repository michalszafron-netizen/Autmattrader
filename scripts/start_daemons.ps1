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

Write-Host "3 okna otwarte. Nie zamykaj ich." -ForegroundColor Green
