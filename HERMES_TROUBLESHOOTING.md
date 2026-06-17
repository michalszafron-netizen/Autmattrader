# Hermes Agent — notatka serwisowa (czytaj to, zanim zaczniesz debugować od zera)

> Jeśli Hermes Desktop coś wywala (czerwony ekran "Hermes couldn't start", Telegram nie
> łączy, gateway nie startuje) — **odeślij Claude'a do tego pliku**, zamiast każdorazowo
> przechodzić całą diagnostykę plik po pliku. Zawiera opis architektury, najczęstsze
> awarie i gotowe komendy naprawcze (stan na 2026-06-11, po migracji konta
> `markowyy` → `krypt`).

## Architektura (gdzie co leży)

- **Desktop app (Electron)**: `C:\Users\krypt\AppData\Local\Programs\Hermes\Hermes.exe`
  - Dane userData (localStorage/leveldb): `C:\Users\krypt\AppData\Roaming\Hermes`
- **Backend / CLI**: `C:\Users\krypt\AppData\Local\hermes\hermes-agent`
  - Konfiguracja: `C:\Users\krypt\AppData\Local\hermes\config.yaml`
  - Logi: `C:\Users\krypt\AppData\Local\hermes\logs\` (najważniejsze: `desktop.log`,
    `gateway.log`, `gateway-restart.log`, `errors.log`)
  - Stan gateway: `C:\Users\krypt\AppData\Local\hermes\gateway_state.json`
- **Środowisko Python**: `C:\Users\krypt\AppData\Local\hermes\hermes-agent\.venv`
  (Python 3.11.15, zarządzane przez `uv`)
  - **WAŻNE**: jest też katalog `venv` (bez kropki) — to **directory junction** wskazujący
    na `.venv`. Desktop ma na sztywno wpisaną ścieżkę `hermes-agent\venv`, więc junction
    musi istnieć, inaczej desktop wywali "No pyvenv.cfg file".
  - `uv.exe`: `C:\Users\krypt\AppData\Local\hermes\bin\uv.exe`
- **Gateway (Telegram/Discord itd.)**: osobny proces Python uruchamiany jako
  **Scheduled Task `Hermes_Gateway`** (Harmonogram zadań Windows), skrypt:
  `C:\Users\krypt\AppData\Local\hermes\gateway-service\Hermes_Gateway.cmd`
- **Zapasowy instalator** (na wypadek gdy desktop zniknie):
  `C:\Users\krypt\AppData\Local\hermes-updater\installer.exe` (v0.15.1, NSIS)

## Znane awarie i naprawy

### 1. "Hermes couldn't start" / czerwony ekran, "No pyvenv.cfg file" lub "ModuleNotFoundError"
Przyczyna: zniknął/uszkodził się `venv` (najczęściej po reinstalacji albo przerwanym
auto-update). Naprawa:
```powershell
cd C:\Users\krypt\AppData\Local\hermes\hermes-agent
# jeśli .venv jest uszkodzony/niekompletny - przebuduj:
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
& C:\Users\krypt\AppData\Local\hermes\bin\uv.exe sync --system-certs --python 3.11
& C:\Users\krypt\AppData\Local\hermes\bin\uv.exe pip install --python .venv\Scripts\python.exe --system-certs pip-system-certs
# upewnij się, że junction venv -> .venv istnieje:
Remove-Item venv -Force -ErrorAction SilentlyContinue   # (tylko jeśli to zwykły folder, nie junction!)
New-Item -ItemType Junction -Path venv -Target .venv
```
Potem zrestartuj desktop (zamknij proces `Hermes` i odpal `Hermes.exe` ponownie) oraz
gateway: `& .venv\Scripts\hermes.exe gateway restart`

### 2. Cała aplikacja Hermes Desktop zniknęła z dysku (brak Hermes.exe, brak skrótów)
Przyczyna: auto-updater Electrona został przerwany w trakcie wymuszonego restartu
Windows Update — zdążył skasować starą wersję, nie zdążył zainstalować nowej.
Naprawa (cichy reinstall z lokalnego cache):
```powershell
Start-Process 'C:\Users\krypt\AppData\Local\hermes-updater\installer.exe' -ArgumentList '/S' -Wait
Start-Process 'C:\Users\krypt\AppData\Local\Programs\Hermes\Hermes.exe'
```
Po reinstalu zwykle trzeba też naprawić venv — patrz punkt 1 (świeży instalator
generuje `.venv`, ale bez `pip-system-certs`, i czasem bez działającego `venv` junction).

### 3. Telegram w gateway: `state: "retrying"`, `"telegram connect timed out"` /
   `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`
Przyczyna: Python/`certifi` w `.venv` nie ufa certyfikatowi, którym Avast skanuje HTTPS
(Windows mu ufa, Python nie). Naprawa:
```powershell
cd C:\Users\krypt\AppData\Local\hermes\hermes-agent
& C:\Users\krypt\AppData\Local\hermes\bin\uv.exe pip install --python .venv\Scripts\python.exe --system-certs pip-system-certs
& .venv\Scripts\hermes.exe gateway restart
```

### 4. System panel: "Messaging gateway stopped" / "gateway-restart · failed"
Przyczyna: usługa gateway nie jest zainstalowana (np. po reinstalacji Windows/zmianie
konta) — restart z poziomu UI "wisi" na interaktywnym pytaniu w konsoli, którego nikt
nie widzi. W `gateway-restart.log` widać: `Gateway service is not installed`.
Naprawa (z terminala, NIE z UI):
```powershell
cd C:\Users\krypt\AppData\Local\hermes\hermes-agent
"Y`nY`nY`n" | .venv\Scripts\hermes.exe gateway install
```
Może wyskoczyć UAC (Harmonogram zadań wymaga uprawnień administratora) — zatwierdź.

### 5. Po zmianie nazwy użytkownika Windows (np. markowyy → krypt)
Sprawdź i podmień ścieżki w (każda zawiera stare `C:\Users\<stara_nazwa>\...`):
- `C:\Users\krypt\AppData\Local\hermes\config.yaml` (sekcja `terminal.cwd`, ścieżki MCP)
- `C:\Users\krypt\AppData\Local\hermes\gateway-service\Hermes_Gateway.cmd`
- `C:\Users\krypt\AppData\Local\hermes\gateway_state.json` (jeśli zawiera martwy PID/stare
  argv — można bezpiecznie nadpisać stanem `"gateway_state":"stopped"`)
- `C:\Users\krypt\AppData\Local\hermes\scripts\check_server.py` (kosmetyczne, dev helper)

## Diagnostyka — od czego zacząć
```powershell
Get-Content C:\Users\krypt\AppData\Local\hermes\gateway_state.json
Get-Content C:\Users\krypt\AppData\Local\hermes\logs\gateway.log -Tail 20
Get-Content C:\Users\krypt\AppData\Local\hermes\logs\gateway-restart.log -Tail 10
Get-Content C:\Users\krypt\AppData\Local\hermes\logs\desktop.log -Tail 20
```

## Telegram — UWAGA, dwa różne boty
- **"Trading AI"** = bot tej sesji Claude Code (ten, z którym teraz piszesz w terminalu).
- **"Trading Hermes"** = bot samego Hermes Agenta (osobna integracja, osobny gateway).
To są dwa zupełnie różne boty/czaty na Telegramie — odpowiedzi Claude'a (przez
`mcp__plugin_telegram_telegram__reply`) zawsze idą do "Trading AI", nigdy do "Trading
Hermes".

---
*Stworzone po sesji naprawczej 2026-06-11: migracja markowyy→krypt, naprawa gateway
service, naprawa SSL (pip-system-certs), odtworzenie zniknietej aplikacji desktop po
przerwanym auto-update, naprawa venv (.venv + junction venv).*
