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

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
app-manager
```

Die App liest Konfigurationen aus `configs/apps/*.json`.
Fuer ein oeffentliches Repo ist nur das Beispiel `configs/apps/example.app.json.example` versioniert.
Lokale App-Configs bleiben bewusst unversioniert und muessen als eigene `*.json`-Dateien unter `configs/apps/` angelegt werden.

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
- Im Dev-Modus werden Laufzeitdateien in `runtime/<app-id>/` geschrieben.
