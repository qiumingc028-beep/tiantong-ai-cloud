"""Run in a network-disabled, root Linux test container; no host installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from ops.r297_evidence_broker import EvidenceBroker, _Handler, _Server
from ops.r297_evidence_storage import provision_acceptance_storage


def main():
    assert sys.platform == "linux" and os.geteuid() == 0
    os.environ["APP_ENV"] = "test"
    roles = {"verifier": 61000, "page_event_receiver": 61001, "authenticated_observer": 61002, "windows_relay": 61003}
    with tempfile.TemporaryDirectory(prefix="r297-peer-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        ledger, nonce = root / "private/runs.json", root / "private/nonces.json"
        provision_acceptance_storage(ledger, nonce)
        broker = EvidenceBroker(run_ledger=ledger, nonce_ledger=nonce, snapshot_root=root / "snapshots", role_uids=roles)
        address = root / "broker.sock"
        with _Server(str(address), _Handler) as server:
            server.broker = broker
            os.chown(address, 0, 61010)
            address.chmod(0o660)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = """
import json, os, sys
from pathlib import Path
from ops.r297_broker_client import broker_request
os.environ['APP_ENV'] = 'acceptance'
os.environ['R297_ACCEPTANCE_BROKER_SOCKET'] = sys.argv[1]
try:
    Path(sys.argv[2]).read_bytes()
    raise AssertionError('root ledger readable by producer/verifier')
except PermissionError:
    pass
result = broker_request(json.loads(sys.argv[3]))
assert result['result'] == sys.argv[4]
"""
            scope = {"namespace": "r297-controlled-canary", "tenant_id": 1, "company_id": 1, "store_id": 7, "platform": "jd", "release_sha": "a" * 40}
            issue = {"action": "issue", "scope": scope, "source_workflow_run_id": 33949515935, "run_attempt": 1}
            checks = 0
            try:
                for role, uid in roles.items():
                    def identity():
                        os.setgroups([])
                        os.setgid(61010)
                        os.setuid(uid)
                    requests = [(issue, "issued", role == "verifier")]
                    if role != "verifier":
                        requests += [({"action": action, "peer_uid": roles["verifier"]}, "", False)
                                     for action in ("validate", "verify", "reserve", "nonce", "begin", "stage", "complete", "recover", "ack")]
                    for request, expected, allowed in requests:
                        result = subprocess.run([sys.executable, "-c", client, str(address), str(ledger), json.dumps(request), expected],
                            preexec_fn=identity, capture_output=True, text=True)
                        if allowed:
                            assert result.returncode == 0, result.stderr
                        else:
                            assert result.returncode != 0 and "R297_BROKER_PERMISSION_DENIED" in result.stderr
                        checks += 1
                assert ledger.stat().st_uid == 0 and ledger.stat().st_mode & 0o777 == 0o600
                assert nonce.stat().st_uid == 0 and nonce.stat().st_mode & 0o777 == 0o600
                print(f"LINUX_REAL_PEER_UID_CHECKS={checks} PASS; ROOT_LEDGER_ISOLATION=PASS")
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    main()
