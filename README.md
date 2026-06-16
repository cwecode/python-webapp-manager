# python-webapp-manager

Windows desktop tool for managing local Python web apps.

It is intended for small internal apps that run on a workstation or terminal server and should be easy to start, stop, update from Git, monitor, or install as a Windows service.

## What It Does

- Connect an existing Python web app with a guided wizard.
- Start and stop a local Python process.
- Detect external processes that already listen on a configured port.
- Check health URLs and show runtime, Git and uptime status.
- Pull app updates with Git and reinstall `requirements.txt`.
- Create and control Windows services through WinSW.
- Keep runtime files, logs and service tools outside the app-manager Git checkout.

## Install

Open `cmd.exe` or PowerShell:

```bat
cd /d C:\Python
git clone <REPOSITORY_URL> App_Manager
cd App_Manager
py -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e .
".venv\Scripts\app-manager.exe"
```

Replace `<REPOSITORY_URL>` with the GitHub URL of this repository or your fork.

## First Start

On first start, choose a manager root. Recommended:

```text
C:\ProgramData\python-webapp-manager
```

The app creates this structure:

```text
C:\ProgramData\python-webapp-manager\
  apps\
  runtime\
  tools\
  logs\
```

Keep this separate from the Git clone, for example:

```text
C:\Python\App_Manager
```

Do not clone the App Manager directly into `C:\ProgramData\python-webapp-manager`; that directory is managed runtime data.

## Connect An App

1. Click `Connect App`.
2. Select a template.
3. Set the app repository path.
4. Set Python/venv paths.
5. Set host, port and optional health URL.
6. Finish and save.

Use `Find Running Apps` when an app is already running and you need to identify or stop the process that owns a port.

## Runtime Modes

- `dev`: App Manager starts a local Python process.
- `prod`: App Manager controls a Windows service through WinSW.
- `both`: Both options are configured, but only one should run on the same port at the same time.
- `observed`: App Manager only observes health/port state and does not start, stop or update the app.

For apps that need network shares, configure the service account on the app's Service page. Example for a local terminal-server user: `.\Jobserver`. Example for a domain user: `DOMAIN\Jobserver`.

## Updates

For connected apps, `Update App` runs:

```bat
git fetch --all --prune
git checkout <branch>
git pull --ff-only --autostash origin <branch>
pip install -r requirements.txt
```

If an app was running, App Manager stops it before the update and starts it again afterwards when possible.

## Important Files

- `configs/manager.json.example`: example manager config.
- `configs/manager.json`: local machine config, ignored by Git.
- `configs/apps/*.json`: local connected app configs, ignored by Git.
- `configs/apps/*.example.json`: example app configs that can be committed.

App configs may contain `service_account` and `service_password` for WinSW. Protect the local manager root because those values are written to the app config and WinSW XML when used.

## More Help

- Windows install notes: `docs/INSTALL_WINDOWS.md`
- Connecting apps: `docs/CONNECTING_APPS.md`
