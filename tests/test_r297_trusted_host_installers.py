from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINUX = (ROOT / "ops" / "install_r297_trusted_linux_host.sh").read_text(encoding="utf-8")
WINDOWS = (ROOT / "ops" / "install_r297_trusted_windows_observer.ps1").read_text(encoding="utf-8")
DATABASE = (ROOT / "ops" / "provision_r297_observer_database.sh").read_text(encoding="utf-8")
RELAY_RECEIPT = (ROOT / "ops" / "install_r297_windows_relay_receipt.ps1").read_text(encoding="utf-8")


def test_endpoint_migration_keeps_existing_password_and_role_units_reload():
    migration = DATABASE.split('if [[ $migrate_endpoint == 1 ]]; then', 1)[1].split('elif [[ $exists == 0 ]]', 1)[0]
    assert 'password=${BASH_REMATCH[1]}' in migration
    assert 'role_sql=' in migration
    assert 'openssl' not in migration and 'ALTER ROLE' not in migration
    role_units = LINUX.split('for role in receiver observer windows-relay;', 1)[1]
    assert role_units.index('systemctl daemon-reload') < role_units.index('systemctl enable')


def test_windows_producer_permissions_reach_children_with_inheritance_disabled():
    for path, rights in (("installStage", "RX"), ("inbox", "RX"), ("outbox", "M"), ("protected", "RX")):
        assert f'& icacls ${path} /grant "$TrustedObserverAccount`:(OI)(CI){rights}" /T /C' in WINDOWS


def test_linux_fixed_sha_install_has_complete_import_closure(tmp_path):
    import re
    import shutil
    import subprocess
    import sys
    files = re.search(r"broker_files=\((.*?)\)", LINUX, re.S).group(1).split()
    assert '"${broker_files[@]}"' in LINUX
    (tmp_path / "ops").mkdir()
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, tmp_path / name)
    result = subprocess.run([sys.executable, "-I", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); from ops.r297_evidence_broker import EvidenceBroker; from ops.r297_broker_client import peer_uid", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_linux_broker_is_keyless_sandboxed_and_owns_both_ledgers():
    broker_unit = LINUX.split("unit=$unit_stage/tiantong-r297-evidence-broker.service", 1)[1].split("install -d -o root -g r297-evidence-producers", 1)[0]
    assert "RestrictAddressFamilies=AF_UNIX" in LINUX
    assert "CapabilityBoundingSet=" in LINUX
    assert "Group=r297-evidence-producers" in LINUX
    assert "NoNewPrivileges=true" in LINUX
    assert "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY" not in broker_unit
    assert "R297_OBSERVER_PRIVATE_KEY" not in broker_unit
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY" not in broker_unit
    assert "--run-ledger /var/lib/tiantong-r297/broker/runs.json" in LINUX
    assert "--nonce-ledger /var/lib/tiantong-r297/broker/nonces.json" in LINUX
    assert "r297-page-receiver" in LINUX
    assert "r297-observer" in LINUX
    assert "r297-verifier" in LINUX
    assert "r297-windows-relay" in LINUX
    assert "systemctl restart tiantong-r297-evidence-broker.service" in LINUX
    assert "for role in receiver observer windows-relay" in LINUX
    assert "RuntimeDirectory=tiantong-r297-$role" in LINUX
    assert 'git -C "$source_root" archive "$source_sha"' in LINUX
    assert '"$staging/$path"' in LINUX
    assert "code_root=/opt/tiantong-r297-evidence/code" in LINUX
    assert 'install -d -o root -g "$producer_group" -m 0750' in LINUX
    assert 'install -d -o root -g "$producer_group" -m 0550 "$install_root"' in LINUX


def test_linux_upgrade_stages_all_units_and_rolls_back_failed_switch():
    assert "unit_stage=$staging/units" in LINUX
    assert "backup_unit_state" in LINUX
    assert "rollback_unit_switch" in LINUX
    assert "trap rollback_unit_switch EXIT" in LINUX
    switch = LINUX.split("switch_started=1", 1)[1]
    first_restart = switch.index("systemctl restart tiantong-r297-evidence-broker.service")
    assert switch.index('install -o root -g root -m 0644 "$unit_stage/$service"') < first_restart
    assert "R297_BROKER_LEDGER_BACKUP=" in LINUX
    assert "R297_BROKER_LEDGER_PAIR_INCOMPLETE" in LINUX
    assert "runs_present != $nonces_present" in LINUX
    assert "sha256sum" in LINUX
    rollback = LINUX.split("rollback_unit_switch()", 1)[1].split("trap rollback_unit_switch EXIT", 1)[0]
    assert rollback.index('systemctl stop "$service"') < rollback.index('if [[ ${had_unit[$service]} == 1 ]]')


def test_windows_installer_separates_candidate_from_fixed_observer():
    assert "R297TrustedWindowsObserver" in WINDOWS
    assert "CandidateAccount" in WINDOWS
    assert "R297_TRUSTED_SIGNER_SHA" in WINDOWS
    assert "PythonRuntimeRoot" in WINDOWS
    assert "PythonExeRelativePath" in WINDOWS
    assert "PythonSha256" in WINDOWS
    assert "PythonRuntimeManifestSha256" in WINDOWS
    assert "R297_PYTHON_MANIFEST_SHA256_MISMATCH" in WINDOWS
    assert "R297_SOURCE_PYTHON_RUNTIME_MISMATCH" in WINDOWS
    assert "R297_WINDOWS_IDENTITY_COLLISION" in WINDOWS
    assert "R297_PYTHON_RELATIVE_PATH_INVALID" in WINDOWS
    assert "R297_PROTECTED_PYTHON_PATH_ESCAPE" in WINDOWS
    assert "PYTHON_RUNTIME_MANIFEST.json" in WINDOWS
    assert "R297_PROTECTED_PYTHON_RUNTIME_MISMATCH" in WINDOWS
    assert "Get-AuthenticodeSignature" in WINDOWS
    assert "python-runtime" in WINDOWS
    assert "/setowner '*S-1-5-32-544' /T /C" in WINDOWS
    assert "R297_UNAUTHORIZED_WRITE_ACE" in WINDOWS
    assert "R297_UNTRUSTED_OWNER" in WINDOWS
    assert "S-1-5-32-544" in WINDOWS
    assert "Assert-LocalNonAdminAccount" in WINDOWS
    assert "Test-LocalGroupContains" in WINDOWS
    assert "R297_TRUSTED_OBSERVER_TASK_RUNNING" in WINDOWS
    assert "Disable-ScheduledTask" in WINDOWS
    assert "Unregister-ScheduledTask" in WINDOWS
    assert "R297_PREVIOUS_TASK_NOT_TRUSTED" in WINDOWS
    assert "R297_TRUSTED_INSTALL_ROLLBACK" in WINDOWS
    assert WINDOWS.index("R297_NEW_INSTALL_VALIDATED") < WINDOWS.rindex("Register-ScheduledTask")
    assert WINDOWS.rindex("Register-ScheduledTask") > WINDOWS.index("R297_UNAUTHORIZED_WRITE_ACE")
    assert "} catch {" in WINDOWS
    assert "git -C $SourceCheckout archive" in WINDOWS
    assert "Join-Path $codeStage $relative" in WINDOWS
    assert "CODE_MANIFEST.json" in WINDOWS
    assert "git -C $SourceCheckout status --porcelain" in WINDOWS
    assert "fsutil reparsepoint query" in WINDOWS
    assert "/inheritance:r" in WINDOWS
    assert "(OI)(CI)RX" in WINDOWS
    assert "(OI)(CI)F" in WINDOWS
    assert "New-Service" not in WINDOWS  # Python is invoked by the trusted scheduled task, not as a fake service binary.
    assert "Register-ScheduledTask" in WINDOWS
    assert "r297_trusted_windows_observer" in WINDOWS
    assert "r297_windows_acceptance.ps1" not in WINDOWS
    assert "install_r297_windows_relay_receipt.ps1" in WINDOWS
    for composite in (
        "FileSystemRights]::Write -bor", "FileSystemRights]::Modify -bor",
        "FileSystemRights]::FullControl -bor",
    ):
        assert composite not in WINDOWS
    for right in (
        "WriteData", "AppendData", "WriteExtendedAttributes", "WriteAttributes",
        "Delete", "DeleteSubdirectoriesAndFiles", "ChangePermissions", "TakeOwnership",
    ):
        assert f"FileSystemRights]::{right}" in WINDOWS


def test_windows_relay_receipt_is_admin_installed_into_protected_root():
    assert "R297_WINDOWS_ADMIN_REQUIRED" in RELAY_RECEIPT
    assert "R297_RELAY_RECEIPT_SHA256_MISMATCH" in RELAY_RECEIPT
    assert "R297_RELAY_RECEIPT_SIDECAR_MISMATCH" in RELAY_RECEIPT
    assert "R297_RELAY_RECEIPT_SCHEMA_INVALID" in RELAY_RECEIPT
    assert "R297TrustedWindowsObserver\\protected" in RELAY_RECEIPT
    assert "$destination = Join-Path $protected 'windows-relay-receipt.json'" in RELAY_RECEIPT
    assert '$destinationSidecar = "$destination.sha256"' in RELAY_RECEIPT
    assert "SetEnvironmentVariable" not in RELAY_RECEIPT


def test_observer_database_role_is_read_only_and_grants_only_three_tables():
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION" in DATABASE
    assert "default_transaction_read_only = on" in DATABASE
    assert "REVOKE ALL ON SCHEMA public" in DATABASE
    assert "public.stores, public.jd_workbench_sync_policies, public.jd_sync_logs" in DATABASE
    assert "R297_OBSERVER_DATABASE_GRANTS=PENDING_RC_MIGRATION" in DATABASE
    assert "chmod 0440" in DATABASE
    assert "root:r297-observer 440" in DATABASE
    assert 'source "$config"' not in DATABASE
    assert "R297_OBSERVER_DATABASE_CONFIG_INVALID" in DATABASE
    assert "chown -h root:r297-observer" in DATABASE
    assert "docker exec -i" in DATABASE
    assert "docker exec -e R297_OBSERVER_PASSWORD" not in DATABASE
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES" in DATABASE
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES" in DATABASE
    assert "actual_grants" in DATABASE
    assert "ALTER ROLE r297_observer PASSWORD" in DATABASE
    assert "NOINHERIT NOREPLICATION NOBYPASSRLS" in DATABASE
    assert "pg_auth_members" in DATABASE
    assert "has_table_privilege" in DATABASE
    assert "R297_OBSERVER_WRITE_PROBE_UNEXPECTED_SUCCESS" in DATABASE
    assert "exists == 0 && -e $config" in DATABASE
def test_windows_installer_rejects_acl_bypass_privileges_and_stale_logons():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "ops/install_r297_trusted_windows_observer.ps1").read_text()
    assert "Get-LocalGroup" in source and "Test-LocalGroupContains $group.SID.Value $sid" in source
    assert "S-1-5-32-551" in source
    assert "secedit /export" in source and "/areas USER_RIGHTS" in source
    for privilege in ("SeBackupPrivilege", "SeRestorePrivilege", "SeDebugPrivilege", "SeImpersonatePrivilege", "SeTakeOwnershipPrivilege"):
        assert privilege in source
    assert "GetOwnerSid" in source and "LOGOFF_REQUIRED" in source
    assert "SeServiceLogonRight = @('S-1-5-6')" in source
    assert "$accountSids -contains $_" in source
