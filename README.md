# python-webapp-manager

Windows-Desktop-Anwendung zum lokalen Verwalten interner Python-Web-Apps in Dev- und Prod-Modus.

## Community

- Contributions are welcome through issues and pull requests.
- Please read `CONTRIBUTING.md` before opening a PR.
- Please follow `SECURITY.md` for vulnerability reports.
- Please follow `CODE_OF_CONDUCT.md` in project discussions and reviews.

## Stand

Der aktuelle Stand ist ein erster vertikaler Slice:

- Add-App-Wizard mit Validierung
- JSON-basierte App-Registry
- Dev-Prozessverwaltung fuer `uvicorn` und `waitress`
- Observed-Modus fuer externe Prozesse ohne Start/Stop/Update
- Health-Checks ueber HTTP
- WinSW-XML-Erzeugung und Service-Command-Wrapper
- WinSW-Suche und Download aus der App heraus
- Einfache PySide6-Oberflaeche fuer Laden, Status, Logs und Kernaktionen

## Start

Ausfuehrliche Installationsschritte fuer Windows und Terminal Server stehen in `docs/INSTALL_WINDOWS.md`.

Kurzinstallation aus GitHub mit `cmd.exe`:

```bat
cd /d C:\Python
git clone https://github.com/cwecode/python-webapp-manager.git App_Manager
cd App_Manager
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .
".venv\Scripts\app-manager.exe"
```

Spaetere Updates des App Managers koennen direkt in der App ueber `Workspace -> Update App Manager` gestartet werden.

### Entwicklung

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
.\.venv\Scripts\app-manager.exe
```

### Betrieb / Server

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\app-manager.exe
```

Beim ersten Start fuehrt dich die App durch eine kurze Einrichtung fuer `apps_dir` und den zentralen Installationsordner unter `C:\ProgramData\python-webapp-manager`.
Das ist absichtlich vom App-Manager-Code unter z. B. `C:\Python\App_Manager` getrennt:

- `C:\Python\App_Manager` enthaelt Git-Clone, `.venv`, Source Code und Self-Update.
- `C:\ProgramData\python-webapp-manager` enthaelt lokale App-Configs, Runtime-State, Tools und Logs.

Clone den App Manager nicht direkt in den Manager-Root unter `C:\ProgramData\python-webapp-manager`, weil dieser Root als verwalteter Datenbereich behandelt wird.
Die empfohlene Struktur ist ein einzelner Root-Ordner:

```text
C:\ProgramData\python-webapp-manager\
  apps\
  runtime\
  tools\
  logs\
```

Im Setup waehlst du deshalb nur den Root-Ordner. Die Unterordner werden automatisch abgeleitet.
Die App prueft dabei im Hintergrund, ob bereits eine WinSW-Installation in typischen Windows-Ordnern vorhanden ist.
Fuer WinSW kannst du dann entweder den verwalteten Standardpfad unter `tools\` verwenden oder einen erkannten bzw. manuell ausgewaehlten Pfad uebernehmen.
Bei Service-Aktionen kopiert die App WinSW pro Service in den jeweiligen Runtime-Ordner, z. B. als `demo-service.exe` neben `demo-service.xml`, weil WinSW EXE und XML mit gleichem Namen nebeneinander erwartet.
Die lokale Maschinenkonfiguration wird als `configs/manager.json` erzeugt und ist bewusst nicht versioniert.

Die App liest Konfigurationen aus `configs/apps/*.json`.
Fuer ein oeffentliches Repo ist nur das Beispiel `configs/apps/example.app.json.example` versioniert.
Lokale App-Configs bleiben bewusst unversioniert und muessen als eigene `*.json`-Dateien unter `configs/apps/` angelegt werden.
Der Modus der Apps (`dev`, `prod`, `both`, `observed`) wird ueber die jeweilige App-Konfiguration gesteuert, nicht ueber `requirements*.txt`.
Neue Apps werden primaer ueber `Add App` angebunden. `Scan Services` ist als Diagnose- und Uebernahmehilfe gedacht, z. B. fuer blockierte Ports oder laufende Altprozesse.

## Konfigurationsformat

Pflichtfelder pro App:

- `id`
- `display_name`
- `mode`
- `repo_path`
- `branch`
- `python_path`
- `venv_path`
- `entry_kind`
- `entry_target`
- `host`
- `port`
- `service_name`
- `log_dir`
- `winsw_exe_path`
- `autostart_prod`

Optionale Felder:

- `health_url`
- `env_file`
- `requirements_file`
- `init_command`

## Hinweise

- Zielplattform ist Windows.
- Service-Management setzt WinSW und passende Rechte voraus.
- Laufzeitdateien, Tools und Logs werden standardmaessig unter `C:\ProgramData\python-webapp-manager\` verwaltet.
- Eine ausfuehrliche Windows-/Terminalserver-Installation steht in `docs/INSTALL_WINDOWS.md`.
- Eine ausfuehrliche Anleitung zum Anbinden bestehender Apps steht in `docs/CONNECTING_APPS.md`.
