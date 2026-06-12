# python-webapp-manager

Windows-Desktop-Anwendung zum lokalen Verwalten interner Python-Web-Apps in Dev- und Prod-Modus.

## Community

- Contributions are welcome through issues and pull requests.
- Please read `CONTRIBUTING.md` before opening a PR.
- Please follow `SECURITY.md` for vulnerability reports.
- Please follow `CODE_OF_CONDUCT.md` in project discussions and reviews.

## Stand

Der aktuelle Stand ist ein erster vertikaler Slice:

- JSON-basierte App-Registry mit Validierung
- Dev-Prozessverwaltung fuer `uvicorn` und `waitress`
- Health-Checks ueber HTTP
- WinSW-XML-Erzeugung und Service-Command-Wrapper
- Einfache PySide6-Oberflaeche fuer Laden, Status, Logs und Kernaktionen

## Start

### Entwicklung

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
app-manager
```

### Betrieb / Server

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
app-manager
```

Beim ersten Start fuehrt dich die App durch eine kurze Einrichtung fuer `apps_dir` und den zentralen Installationsordner unter `C:\ProgramData\python-webapp-manager`.
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
Die lokale Maschinenkonfiguration wird als `configs/manager.json` erzeugt und ist bewusst nicht versioniert.

Die App liest Konfigurationen aus `configs/apps/*.json`.
Fuer ein oeffentliches Repo ist nur das Beispiel `configs/apps/example.app.json.example` versioniert.
Lokale App-Configs bleiben bewusst unversioniert und muessen als eigene `*.json`-Dateien unter `configs/apps/` angelegt werden.
Der Modus der verwalteten Apps (`dev`, `prod`, `both`) wird ueber die jeweilige App-Konfiguration gesteuert, nicht ueber `requirements*.txt`.

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
