from __future__ import annotations

import json

from app_manager.core.service_inspect import (
    ServiceInspector,
    accounts_match,
    network_account_warning,
    normalize_account,
)


def test_inspect_parses_service_record() -> None:
    payload = json.dumps(
        {
            "Name": "zilhub",
            "StartName": r"igefa\jobserver",
            "State": "Running",
            "ProcessId": 4321,
            "PathName": r"C:\runtime\zilhub.exe",
        }
    )
    inspector = ServiceInspector(shell_runner=lambda script: payload)

    info = inspector.inspect("zilhub")

    assert info.exists is True
    assert info.start_name == r"igefa\jobserver"
    assert info.state == "Running"
    assert info.process_id == 4321
    assert info.path_name == r"C:\runtime\zilhub.exe"


def test_inspect_handles_missing_service() -> None:
    inspector = ServiceInspector(shell_runner=lambda script: "null")

    info = inspector.inspect("missing")

    assert info.exists is False
    assert info.start_name is None


def test_inspect_handles_empty_output() -> None:
    inspector = ServiceInspector(shell_runner=lambda script: "")

    assert inspector.inspect("missing").exists is False


def test_accounts_match_treats_localsystem_aliases_as_equal() -> None:
    assert accounts_match(None, "LocalSystem") is True
    assert accounts_match(None, r"NT AUTHORITY\SYSTEM") is True
    assert accounts_match("", "LocalSystem") is True


def test_accounts_match_detects_localsystem_fallback() -> None:
    assert accounts_match(r"igefa\jobserver", "LocalSystem") is False


def test_accounts_match_is_case_insensitive() -> None:
    assert accounts_match(r"IGEFA\Jobserver", r"igefa\jobserver") is True


def test_accounts_match_local_dot_prefix() -> None:
    assert accounts_match(r".\Jobserver", "Jobserver") is True


def test_network_account_warning_flags_builtin_accounts() -> None:
    assert network_account_warning("LocalSystem") is not None
    assert network_account_warning(r"NT AUTHORITY\SYSTEM") is not None
    assert network_account_warning(r"NT AUTHORITY\NetworkService") is not None
    assert network_account_warning(None) is not None


def test_network_account_warning_allows_user_accounts() -> None:
    assert network_account_warning(r"igefa\jobserver") is None
    assert network_account_warning(r".\Jobserver") is None


def test_normalize_account_strips_local_prefix() -> None:
    assert normalize_account(r".\Jobserver") == "jobserver"
    assert normalize_account("LocalSystem") == "localsystem"
