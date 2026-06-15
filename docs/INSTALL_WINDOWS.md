# Windows and Terminal Server Installation

This guide explains how to install `python-webapp-manager` from GitHub on a Windows machine or Terminal Server.

## Prerequisites

Install these once on the server:

- Python 3.12 or newer
- Git for Windows
- optional: GitHub CLI, useful for private repositories

If `winget` is available, run this in `cmd.exe`:

```bat
winget install --id Python.Python.3.12 -e
winget install --id Git.Git -e
winget install --id GitHub.cli -e
```

After installing Python or Git, close and reopen `cmd.exe` so `python`, `py`, `git`, and `gh` are available in `PATH`.

## Install App Manager From GitHub

Recommended location:

```text
C:\Python\App_Manager
```

Run this in `cmd.exe`:

```bat
cd /d C:\Python
git clone https://github.com/cwecode/python-webapp-manager.git App_Manager
cd App_Manager

py -m venv .venv
.venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -e .

app-manager
```

If `py` is not available, use:

```bat
python -m venv .venv
```

## PowerShell Variant

```powershell
cd C:\Python
git clone https://github.com/cwecode/python-webapp-manager.git App_Manager
cd App_Manager

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e .

app-manager
```

If PowerShell blocks script activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then open a new PowerShell window and activate the venv again.

## First Start

On first start App Manager asks for a manager root directory.

Recommended root:

```text
C:\ProgramData\python-webapp-manager
```

App Manager creates this structure below the root:

```text
C:\ProgramData\python-webapp-manager\
  apps\
  runtime\
  tools\
  logs\
```

Local machine configuration is stored in `configs\manager.json` and should not be committed to Git.

## Updating App Manager Itself

Run this in `cmd.exe`:

```bat
cd /d C:\Python\App_Manager
git pull
.venv\Scripts\activate.bat
pip install -e .
app-manager
```

## Connecting Private GitHub Repositories

App Manager checks updates for managed web apps through normal Git commands.
Each managed web app needs a local Git clone on the server. The local clone has a remote such as `origin` that points to GitHub.

For private repositories, authenticate Git once for the Windows user that runs App Manager.

GitHub CLI example:

```bat
gh auth login
gh repo clone OWNER/PRIVATE_REPO C:\Python\your_web_app
```

Then verify the clone:

```bat
cd /d C:\Python\your_web_app
git remote -v
git fetch origin main --prune
git status
```

If those commands work in the same Windows user session, App Manager can also check that repository.

## How Update Checks Work

For a connected app with `repo_path=C:\Python\your_web_app` and `branch=main`, App Manager does this during refresh:

```bat
git fetch origin main --prune
git rev-list --left-right --count HEAD...origin/main
```

If the local clone is behind `origin/main`, the UI shows `update available`.

When you click `Update`, App Manager runs:

```bat
git fetch --all --prune
git checkout main
git pull --ff-only origin main
```

Then it installs `requirements.txt` if configured or present, runs the optional init command, and restarts the previously active runtime when possible.

## Terminal Server Notes

- Install and run App Manager under the same Windows user that should manage the apps.
- GitHub credentials are user-specific. A clone that works for one user may not work for another.
- If you later run service actions, some WinSW operations require administrator rights.
- Keep app configs, logs, tools, and runtime files outside the Git repository, preferably under `C:\ProgramData\python-webapp-manager`.

## Troubleshooting

`git` is not recognized:

```bat
winget install --id Git.Git -e
```

Then reopen `cmd.exe`.

`python` or `py` is not recognized:

```bat
winget install --id Python.Python.3.12 -e
```

Then reopen `cmd.exe`.

Private GitHub repository cannot be fetched:

```bat
gh auth status
gh auth login
```

Then test the app repository manually:

```bat
cd /d C:\Python\your_web_app
git fetch origin main --prune
```

Working tree has local changes:

```bat
cd /d C:\Python\your_web_app
git status
```

App Manager intentionally blocks updates when local files have uncommitted changes.
