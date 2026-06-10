# Contributing

Thanks for contributing to `python-webapp-manager`.

## Ground rules

- Keep changes small and reviewable.
- Prefer incremental improvements over broad refactors.
- Follow the existing architecture and conventions.
- Do not include secrets, private keys, tokens, or real `.env` values.

## Local setup

```powershell
py -3.9 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[dev]
```

## Development workflow

1. Open an issue for larger changes before starting implementation.
2. Create a branch from `main`.
3. Add or update tests when behavior changes.
4. Run the smallest relevant checks before opening a pull request.

## Checks

```powershell
pytest -q
```

## Pull requests

- Describe the user-visible change and the reason for it.
- Mention tradeoffs or follow-up work if relevant.
- Keep PRs focused on one concern.
- Update documentation when setup, behavior, or configuration changes.

## Security

If you find a security issue, do not open a public issue.
Follow the reporting guidance in `SECURITY.md`.
