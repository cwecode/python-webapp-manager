# python-webapp-manager

Windows desktop tool for managing local Python web apps. The application window is titled **Python WebApp Manager**.

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

`pip install -e .` registers an `app-manager` entry point, so `.venv\Scripts\app-manager.exe` is the program you start from now on (see [Start, Stop & Restart](#start-stop--restart)).

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

## Start, Stop & Restart

The manager is a normal desktop window, not a background service. Start it when you want to look at or change something, and close it when you are done.

**Closing the manager does not stop anything.** The Windows services and local app processes it manages keep running on their own; the manager re-attaches to them the next time you open it. So if you close the window by accident on a server, your apps stay online — just reopen the manager when you need it.

Start it with the `app-manager` entry point that `pip install -e .` created. From the project folder:

```bat
.venv\Scripts\app-manager.exe
```

Or, with the virtual environment activated (`.venv\Scripts\activate`), simply:

```bat
app-manager
```

It opens without a console window; you only see a console if you started it from one. To **restart**, close the window and start it again — no cleanup needed.

### Optional: a desktop icon

If you would rather double-click an icon than type a command, create a shortcut once. Run this from the project folder in PowerShell (one line):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Python WebApp Manager.lnk"); $s.TargetPath = "$PWD\.venv\Scripts\app-manager.exe"; $s.WorkingDirectory = "$PWD"; $s.Save()
```

This drops a `Python WebApp Manager` icon on your desktop that points at the entry point. To also pin it to the Start menu, right-click the icon → **Pin to Start**.

## Connect An App

1. Click the `+` button above the app list.
2. Select a template.
3. Set the app repository path.
4. Set Python/venv paths.
5. Set host, port and optional health URL.
6. Finish and save.

Use the search button (`⌕`) above the app list to scan local ports and services when an app is already running and you need to identify or stop the process that owns a port.

The app list refreshes automatically in the background, so there is no manual refresh button. Each row has a wrench button to edit that app's config and an update button to pull it from Git; the update button highlights when an update is available.

## Runtime Modes

- `dev`: runs the app as a local Python process.
- `prod`: controls a Windows service through WinSW.
- `both`: Both options are configured, but only one should run on the same port at the same time.
- `observed`: only observes health/port state and does not start, stop or update the app.

For apps that need a specific account (for example to reach network shares), configure the service account on the app's Service page. Example for a local terminal-server user: `.\Jobserver`. Example for a domain user: `DOMAIN\Jobserver`. The main service buttons are intentionally reduced to `Apply + Start Service` and `Stop + Remove Service` so service changes are applied cleanly without redundant actions. `Service Diagnose` shows the account Windows actually runs the service under and warns when it differs from the configured account (for example when a service silently fell back to a built-in account such as `LocalSystem`).

## Updates

For connected apps, the per-row update button runs:

```bat
git fetch --all --prune
git checkout <branch>
git pull --ff-only --autostash origin <branch>
pip install -r requirements.txt
```

If an app was running, it is stopped before the update and started again afterwards when possible.

Because `--ff-only` is used, local commits are never overwritten: a branch that has diverged from its remote makes the update abort instead. Uncommitted edits are stashed with `--autostash` and re-applied afterwards. When an app has local changes that are not on GitHub (uncommitted edits or unpushed commits), the update button asks for confirmation first, so you cannot accidentally update an app you are actively developing on this machine.

## Important Files

- `configs/manager.json.example`: example manager config.
- `configs/manager.json`: local machine config, ignored by Git.
- `configs/apps/*.json`: local connected app configs, ignored by Git.
- `configs/apps/*.example.json`: example app configs that can be committed.

App configs may contain `service_account` and `service_password` for WinSW. Protect the local manager root because those values are written to the app config and WinSW XML when used.

## More Help

- Windows install notes: `docs/INSTALL_WINDOWS.md`
- Connecting apps: `docs/CONNECTING_APPS.md`
