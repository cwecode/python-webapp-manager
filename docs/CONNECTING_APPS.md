# Connecting Python Web Apps

This guide describes the recommended way to connect an existing Python web app to `python-webapp-manager`.

## What App Manager Can Control

App Manager needs a reproducible start command. A listening port alone is useful for discovery, but it is not enough to reliably restart or update an app.

Supported app shapes:

- `uvicorn` for FastAPI, Starlette, and other ASGI apps
- `waitress` for Flask and other WSGI apps on Windows
- WinSW-backed Windows services for production-style service management

## Minimal Requirements

For a fully manageable app, provide:

- project root path
- Python interpreter path
- virtual environment path
- entry kind: `uvicorn` or `waitress`
- entry target, for example `main:app`, `app.main:app`, or `wsgi:app`
- host and port
- optional health URL
- optional requirements file
- optional init command

## Recommended Workflow

Use `Add App` as the primary path.

1. Enter the app basics: ID, display name, mode, host, port, and health URL.
2. Enter the runtime paths: repo, branch, Python executable, venv, entry kind, and entry target.
3. Enter service/log fields if you want `prod` or `both`.
4. Finish the wizard. App Manager validates paths, importability, and port status before saving.

Use `Scan Services` only as a helper when you need to inspect local listeners, find a blocked port, ignore noise, or attach a running non-service process so it can be stopped once.

## Modes

Use `dev` when App Manager should start and stop a normal Python process.

Use `prod` when the app should be managed as a Windows service through WinSW.

Use `both` only when you deliberately want both workflows for the same app.

Use `observed` when you only want to document and observe an external process. Observed apps can show port and health status, but App Manager will not start, stop, update, or install services for them.

## Recommended App Contract

Keep the target app easy to manage by following this small contract:

- Put the app in a Git repository.
- Use a project-local virtual environment, usually `.venv`.
- Provide `requirements.txt` for server installs.
- Expose a health endpoint such as `/health`.
- Keep secrets in `.env`, not in JSON configs.
- Make the start command reproducible from the project root.

FastAPI start example:

```powershell
C:\apps\demo-api\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080
```

FastAPI health endpoint:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Flask/Waitress start example:

```powershell
C:\apps\demo-api\.venv\Scripts\waitress-serve.exe --host 0.0.0.0 --port 8080 wsgi:app
```

Flask health endpoint:

```python
from flask import Flask

app = Flask(__name__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

## WinSW

WinSW is only needed for `prod` and `both`.

Recommended setup:

1. Open `Settings`.
2. Choose the `python-webapp-manager` root directory.
3. Let the app search for an existing WinSW executable.
4. If none is found, click `Download WinSW`.
5. Keep the managed default path under `tools\` unless your server already has a centrally managed WinSW binary.

The app downloads the current release asset matching the machine architecture from the official WinSW GitHub releases.

When a service action runs, App Manager writes `<service_name>.xml` into the app runtime directory and copies the configured WinSW executable there as `<service_name>.exe`.
WinSW expects the executable and XML file to have the same base name and live next to each other.

Run `Install Service` once before using `Start Service`, `Stop Service`, or `Restart Service`.
If Windows reports that the service is not installed, App Manager treats the service as stopped and asks you to install it first.

## Finding a Blocked Port

Use `Scan Services` when you need to identify what is blocking a port.

Workflow:

1. Start `python-webapp-manager` on the server.
2. Click `Scan Services`.
3. Sort the table by `Port`.
4. Select the row for the blocked port.
5. Review the detected PID, process, executable path, and service name.

If the process is not a Windows service, the scan dialog can attach the current PID.
When attached, `Stop Dev` can stop that running process through App Manager.

This is intended for takeover and cleanup of an existing process. After that, fill in the real project paths and entry target so App Manager can start it again later.

## Importing From Scan

The scan can prefill a config, but some fields must still be reviewed.

Fields that are usually reliable:

- `host`
- `port`
- `pid`
- process name
- executable path
- Windows service name, when detected

Fields that often need manual correction:

- `repo_path`
- `python_path`
- `venv_path`
- `entry_kind`
- `entry_target`
- `health_url`

Use `Attach current PID so Stop Dev can stop this running process` only when you want App Manager to take over the current process for stopping. This does not magically reconstruct the original start command.

## Health Checks

A health endpoint makes the UI much more useful.

Recommended response:

```json
{"status": "ok"}
```

Recommended URL:

```text
http://127.0.0.1:8080/health
```

Bind the app to `0.0.0.0` when it should accept network traffic, but use `127.0.0.1` in the health URL when App Manager runs on the same server.

## Updates

For GitHub-backed updates, see `docs/INSTALL_WINDOWS.md` for the full server setup and private repository authentication workflow.

The update action expects:

- `repo_path` is a Git repository
- `branch` exists
- `python_path` exists
- `requirements_file` exists or `repo_path\requirements.txt` exists

Update performs:

1. stop active runtime, if App Manager knows one is active
2. `git fetch --all --prune`
3. `git checkout <branch>`
4. `git pull --ff-only --autostash origin <branch>`
5. `pip install -r requirements.txt`, if present
6. optional init command
7. restart the previously active runtime

If the working tree has local changes, Git temporarily stashes them with `--autostash` and applies them again after the pull.
If Git reports a conflict, resolve it in the app repository and run Update again.

Typical dirty files are generated runtime data such as:

- `data/*.json`
- `*.log`
- local exports
- report recipient lists
- uploaded/generated files

Best practice: keep mutable app data outside the Git checkout, for example under `C:\ProgramData\<your-app>`, or add generated files to `.gitignore`.
If such files are already tracked by Git, `.gitignore` alone is not enough. Remove them from tracking once and commit that cleanup:

```bat
git rm --cached data\voortman_pipes.json
git rm --cached data\voortman_pipes_archived.json
git rm --cached data\xml_export_counter.json
git commit -m "Stop tracking generated runtime data"
```

Only do this for files that are truly generated/local runtime data and should not come from GitHub.

## Practical Server Takeover

When an old Python server is stuck on a port:

1. Scan services.
2. Sort by port.
3. Select the blocked port.
4. Save the config with attach enabled.
5. Use `Stop Dev` to stop the attached PID.
6. Correct `repo_path`, `python_path`, `venv_path`, and `entry_target`.
7. Use `Start Dev` to start the app through App Manager.
8. Add a health URL and verify with `Check Health`.

After that, the app is manageable through the normal App Manager flow.

For an app that is already configured but still has an external process listening on its port:

1. Select the app.
2. Confirm the status detail shows an external PID listening on the configured host and port.
3. Click `Stop External PID` to force-stop that process.
4. For service mode, click `Install Service` once.
5. Then use `Start Service`, `Stop Service`, or `Restart Service` normally.
