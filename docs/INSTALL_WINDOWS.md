# Windows Installation

This guide is the short version for Windows workstations and terminal servers.

## Requirements

- Windows 10/11 or Windows Server
- Python 3.9 or newer
- Git for Windows

Install missing tools:

```bat
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
```

Close and reopen the terminal afterwards.

## Install App Manager

```bat
cd /d C:\Python
git clone <REPOSITORY_URL> App_Manager
cd App_Manager
py -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e .
".venv\Scripts\app-manager.exe"
```

Use the GitHub URL of this repository or your fork for `<REPOSITORY_URL>`.

## First Start

Use this manager root unless you have a reason to choose another path:

```text
C:\ProgramData\python-webapp-manager
```

This keeps runtime data away from the App Manager source code:

```text
C:\Python\App_Manager                  source code and .venv
C:\ProgramData\python-webapp-manager   app configs, runtime state, tools, logs
```

## Updating App Manager

Use the button:

```text
Workspace -> Update App Manager
```

Manual fallback:

```bat
cd /d C:\Python\App_Manager
git pull
".venv\Scripts\python.exe" -m pip install -e .
".venv\Scripts\app-manager.exe"
```

## Private App Repositories

App Manager uses normal Git credentials for the Windows user running the app.

Test private repository access manually first:

```bat
cd /d C:\Python\your_web_app
git fetch origin main --prune
```

If that works in the same Windows user session, App Manager can use it too.

Useful GitHub CLI setup:

```bat
winget install --id GitHub.cli -e
gh auth login
```

## Windows Service Notes

- Service actions may require Administrator rights.
- Services are created through WinSW.
- App Manager can download or reuse an existing WinSW executable.
- Do not run a local app process and a Windows service on the same host/port at the same time.
- If the service must access a UNC path or other network share, configure a service account that has those permissions.
- After changing a service account, stop and uninstall the existing service, then install and start it again.

Example service account values:

```text
Local server user: .\Jobserver
Domain user:       DOMAIN\Jobserver
```

## Troubleshooting

`git` not found:

```bat
winget install --id Git.Git -e
```

`python` or `py` not found:

```bat
winget install --id Python.Python.3.12 -e
```

App update fails:

```bat
cd /d C:\Python\your_web_app
git status
git pull --ff-only --autostash origin main
```

Port is blocked:

1. Open App Manager.
2. Click `Find Running Apps`.
3. Find the row with the blocked port.
4. Use `Stop External Listener` only when you are sure the process belongs to the app you want to manage.
