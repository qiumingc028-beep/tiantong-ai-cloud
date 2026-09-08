from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINUX = (ROOT / "ops" / "install_r297_trusted_linux_host.sh").read_text(encoding="utf-8")
WINDOWS = (ROOT / "ops" / "install_r297_trusted_windows_observer.ps1").read_text(encoding="utf-8")
DATABASE = (ROOT / "ops" / "provision_r297_observer_database.sh").read_text(encoding="utf-8")


def test_linux_broker_is_keyless_sandboxed_and_owns_both_ledgers():
    assert "RestrictAddressFamilies=AF_UNIX" in LINUX
    assert "CapabilityBoundingSet=" in LINUX
    assert "Group=r297-evidence-producers" in LINUX
    assert "NoNewPrivileges=true" in LINUX
    assert "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY" not in LINUX
    assert "R297_OBSERVER_PRIVATE_KEY" not in LINUX
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY" not in LINUX
    assert "--run-ledger /var/lib/tiantong-r297/broker/runs.json" in LINUX
    assert "--nonce-ledger /var/lib/tiantong-r297/broker/nonces.json" in LINUX
    assert "r297-page-receiver" in LINUX
    assert "r297-observer" in LINUX
    assert "r297-verifier" in LINUX
    assert "r297-windows-relay" in LINUX


def test_windows_installer_separates_candidate_from_fixed_observer():
    assert "R297TrustedWindowsObserver" in WINDOWS
    assert "CandidateAccount" in WINDOWS
    assert "R297_TRUSTED_SIGNER_SHA" in WINDOWS
    assert "PythonRuntimeRoot" in WINDOWS
    assert "PythonExeRelativePath" in WINDOWS
    assert "PythonSha256" in WINDOWS
    assert "Get-AuthenticodeSignature" in WINDOWS
    assert "python-runtime" in WINDOWS
    assert "/setowner '*S-1-5-32-544' /T /C" in WINDOWS
    assert "R297_UNAUTHORIZED_WRITE_ACE" in WINDOWS
    assert "R297_UNTRUSTED_OWNER" in WINDOWS
    assert "S-1-5-32-544" in WINDOWS
    assert "git -C $SourceCheckout status --porcelain" in WINDOWS
    assert "fsutil reparsepoint query" in WINDOWS
    assert "/inheritance:r" in WINDOWS
    assert "(OI)(CI)RX" in WINDOWS
    assert "(OI)(CI)F" in WINDOWS
    assert "New-Service" not in WINDOWS  # Python is invoked by the trusted scheduled task, not as a fake service binary.
    assert "Register-ScheduledTask" in WINDOWS
    assert "r297_trusted_windows_observer" in WINDOWS
    assert "r297_windows_acceptance.ps1" not in WINDOWS


def test_observer_database_role_is_read_only_and_grants_only_three_tables():
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION" in DATABASE
    assert "default_transaction_read_only = on" in DATABASE
    assert "REVOKE ALL ON SCHEMA public" in DATABASE
    assert "public.stores, public.jd_workbench_sync_policies, public.jd_sync_logs" in DATABASE
    assert "R297_OBSERVER_DATABASE_GRANTS=PENDING_RC_MIGRATION" in DATABASE
    assert "chmod 0400" in DATABASE
