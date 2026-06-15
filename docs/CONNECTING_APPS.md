# Connecting Apps

This guide explains how to connect any local Python web app.

## Basic Rule

App Manager needs a reproducible start command:

```text
repo path + Python/venv + entry target + host + port
```

A listening port alone is useful for discovery, but it is not enough to reliably restart or update an app.

## Connect A Normal Python App

1. Click `Connect App`.
2. Choose a template.
3. Set `repo_path` to the app Git checkout.
4. Set `python_path` to the venv Python executable.
5. Set `venv_path` to the venv folder.
6. Set `entry_kind` and `entry_target`.
7. Set host, port and optional health URL.
8. Finish the wizard.

Common examples:

```text
FastAPI / Uvicorn: entry_kind=uvicorn, entry_target=main:app
Flask / Waitress:  entry_kind=waitress, entry_target=wsgi:app
```

## Runtime Modes

- `dev`: App Manager starts and stops a local Python process.
- `prod`: App Manager controls a Windows service through WinSW.
- `both`: Both options are configured, but only one should run on the same port at once.
- `observed`: App Manager only watches health/port state.

Use `both` only when you intentionally want both management options. The UI prevents starting a process and service at the same time for the same app.

## Existing Running Apps

Use `Find Running Apps` when an app is already running.

Recommended takeover flow:

1. Click `Find Running Apps`.
2. Select the listener for the app port.
3. Save the generated config.
4. If needed, attach the current PID.
5. Use `Stop App Process` or `Stop External Listener` to clear the port.
6. Correct repo, Python, venv and entry fields.
7. Start the app through App Manager.

Only stop external listeners when you are sure the PID belongs to the app you want to manage.

## Health Checks

The health URL is optional but recommended:

```text
http://127.0.0.1:8000/health
```

The status cards refresh automatically. `Recheck Health` runs the health check immediately.

## Git Updates

`Update App` expects:

- `repo_path` is a Git repository.
- `branch` exists.
- `python_path` exists.
- `requirements.txt` exists or is configured when dependencies should be installed.

Update runs:

```bat
git fetch --all --prune
git checkout <branch>
git pull --ff-only --autostash origin <branch>
pip install -r requirements.txt
```

Local changes are temporarily stashed by Git during pull. If Git reports a conflict, resolve it in the app repository and run the update again.

## Runtime Data

Keep mutable runtime data outside the Git checkout whenever possible:

```text
C:\ProgramData\<your-app>\data
C:\ProgramData\<your-app>\uploads
C:\ProgramData\<your-app>\logs
```

If an app writes generated files into the Git checkout, add those files to the app repository's `.gitignore`.

If generated files are already tracked by Git, remove them from tracking once:

```bat
git rm --cached path\to\generated-file.json
git commit -m "Stop tracking generated runtime data"
```

Only do this for files that are truly generated/local runtime data.

## Windows Services

For service mode:

1. Configure `mode=prod` or `mode=both`.
2. Set `service_name`.
3. Set or download WinSW.
4. Click `Install Service`.
5. Use `Start Service`, `Stop Service`, or `Restart Service`.

Some service actions require Administrator rights.
