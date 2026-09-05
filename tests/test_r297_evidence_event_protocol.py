from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys

import pytest

from ops.r297_evidence_events import load_trust_manifest, verify_acceptance_event_bundle
from tests.test_r291_jd_workbench_cloud import TEST_RSA_D, TEST_RSA_N_B64


_PAGE_N = "yZNc_C6r9P7c1DgsOoyxwx2xaJq-NQx0C-2nkJgx0FTeTsL-usd7DVMEXMXHh-IHZEy_rgC43cGo41RgbIXJgEBmffUGjz3I5LH_w3LGs9aJaNnkalHRGJFzKgH5Qz7o9mj65asJ2GGZUl6qEOZ7wmrApOZmGzQ6FQ8cPD6u3Cl5GaFBJpnvE1QL2Rzpg90AEFIeRLU_9d1zy53mBtXE6GwPljagVaaotw4GZrgxBquOd8Q0_IQf-MLEdgwhksw6lbUQuEfVb4JW0tuxVd0F9iBtQTSNKXMiW8d0hxBQ1FzLfcjBXQgfhaY9-BHp3yp8hfPiDjmW7917mj3oPL-odQ"
_PAGE_D = "BXdB8q3bw4JO5zy5KMLQNLKxk3C2H_WCBtKfXfKsY21TjPH1k4ebDYI1scPYFbOi3OgBF4DI5PbIIlvEb7uqNWdOkWS2bPnCiAN3S9CuAR3DXaHdX5LR6b1msxxxqqI16lTmGfx-snaWu2sOBX5fYLqrZHSt-38q5KNK3ma3zZH8vmdXpxwEgW0u9sSiSKmE1oAxlYcxQVjGXwU37hGQ3yvO-1Q3MoPlRrwW7Nyxd7ADjIQHbwbR7-YeiSJUZmAVApqGdY9cyI53X6kvmQ9fg_v_NhU667J6LFaZkm3lIJloOnPJTFnYDnxjZW7XnDr_fgqXFPjw3dfkr33oo_rQyQ"
_WINDOWS_N = "3gopfQl3LtI1-yVIGGVF5wrt7ab-Z5rj-N36Efuy7gFv428S5KyQFf_JXvl_StuiIcnb44I44hVUdZMeBAlAFvnoCyagOI8sU2TDkm0PoZGGHuXRBYN4j76O13gwqzRoB7Bj1O-XMhxECvfz6F5fTd9zzpSWqfF7afVZUGM7nYRB84Wdarh3hpftcTmsuvpczTsGhjlzt5v2gUq_mMVHkFK_Xi10LLwhIEubgmsYASG5Ui9gtpusqL9fY3foaAsovvs8Ukx3Gs0IBV4MeUwzJ-_ern932h36DgdCoaqdg20E3HTbxz0GKKXRMMwT1JdJCHMewGukTcAiPgmCsIz8JQ"
_WINDOWS_D = "AqmBB1aAdw9-pbDz_RTjwmojYaTNqozVHGP-7k3D_q4GOyYXBiZagOUE805O_CUHe9u5dvAWAgHq9hDqPHam7c-XvGB9bcgrqiFMZfpIRHHj94VeXPBPVvvcJxGyFa9maucuvzwTJj7oAvCnnDrbbinWb9zgtI9oYSQXqsrRyWjpkOpXl24zar_Nb9lfSPpvBVDvIGOLusvN74EQuhtW8xP8XcwbwHNat_cRqAoo3xiNEIpDuQxJxxwXjj6lZ6kaTRFSzYkwU9aq6zTjI2-C6QR0-AylViqWEOd2o-FNojAwS7rTKeCjiil2bIv97nJOzZGjMIyt-AMoTGeje9We2Q"
_PRIVATE_KEYS = {
    "page_event_receiver": (_PAGE_N, _PAGE_D),
    "authenticated_observer": (TEST_RSA_N_B64, base64.urlsafe_b64encode(TEST_RSA_D.to_bytes(256, "big")).rstrip(b"=").decode()),
    "windows_runner": (_WINDOWS_N, _WINDOWS_D),
}


@pytest.fixture(autouse=True)
def _use_test_trust_manifest(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")


def test_embedded_test_trust_manifest_is_versioned_and_role_scoped():
    manifest, digest = load_trust_manifest(environment="test")

    assert manifest["schema_version"] == 1
    assert manifest["environment"] == "test"
    assert digest == "0eac4b3fc49f913f33762dbedbe41916c3ef50eb1128211d7d93281c78902fed"
    assert all("d" not in key and "private_key" not in key for key in manifest["keys"])
    assert {key["issuer"] for key in manifest["keys"]} == set(_PRIVATE_KEYS)
    assert {key["algorithm"] for key in manifest["keys"]} == {"RS256"}
    assert len({key["key_id"] for key in manifest["keys"]}) == 3
    assert {
        key["issuer"]: key["allowed_event_types"]
        for key in manifest["keys"]
    } == {
        "page_event_receiver": ["web_page_close"],
        "authenticated_observer": ["authenticated_observer"],
        "windows_runner": ["electron_exit"],
    }


def test_production_rejects_test_fixture_trust_manifest():
    from ops import r297_evidence_events

    source = r297_evidence_events._TEST_TRUST_MANIFEST
    relabelled = json.loads(source.read_text())
    relabelled["environment"] = "production"
    relabelled["manifest_id"] = "r297-evidence-trust-production-v1"
    for key in relabelled["keys"]:
        key["key_id"] = key["key_id"].removesuffix("-test") + "-production"
    with pytest.raises(ValueError, match="test evidence key forbidden in production"):
        r297_evidence_events._validate_trust_manifest(relabelled, environment="production")


def test_production_rejects_equivalent_test_key_encoding():
    from ops import r297_evidence_events

    relabelled = json.loads(r297_evidence_events._TEST_TRUST_MANIFEST.read_text())
    relabelled["environment"] = "production"
    relabelled["manifest_id"] = "r297-evidence-trust-production-v1"
    for key in relabelled["keys"]:
        key["key_id"] = key["key_id"].removesuffix("-test") + "-production"
        key["n"] = base64.urlsafe_b64encode(b"\0" + base64.urlsafe_b64decode(
            key["n"] + "=" * (-len(key["n"]) % 4)
        )).rstrip(b"=").decode()

    with pytest.raises(ValueError, match="test evidence key forbidden in production"):
        r297_evidence_events._validate_trust_manifest(relabelled, environment="production")


def test_manifest_rejects_equivalent_key_encodings_for_different_roles():
    from ops import r297_evidence_events

    manifest = json.loads(r297_evidence_events._TEST_TRUST_MANIFEST.read_text())
    page_key = manifest["keys"][0]
    observer_key = manifest["keys"][1]
    observer_key["n"] = base64.urlsafe_b64encode(b"\0" + base64.urlsafe_b64decode(
        page_key["n"] + "=" * (-len(page_key["n"]) % 4)
    )).rstrip(b"=").decode()
    observer_key["e"] = page_key["e"]

    with pytest.raises(ValueError, match="evidence issuer keys not isolated"):
        r297_evidence_events._validate_trust_manifest(manifest, environment="test")


def _scope() -> dict:
    return {
        "namespace": "r297-acceptance-9b466ac80122",
        "tenant_id": "tenant-1",
        "company_id": "company-1",
        "store_id": 7,
        "platform": "jd",
        "release_sha": "9b466ac80122e35893cbaa408735136acc88331a",
    }


def _integer(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")


def _sign(event: dict) -> dict:
    modulus_b64, private_b64 = _PRIVATE_KEYS[event["issuer"]]
    event = {**event, "key_id": f"r297-{event['issuer']}-test"}
    canonical = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(canonical).digest()
    encoded = b"\x00\x01" + b"\xff" * (256 - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), _integer(private_b64), _integer(modulus_b64)).to_bytes(256, "big")
    return {**event, "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode()}


def _bundle(now: datetime) -> dict:
    common = _scope()
    page = _sign({
        **common,
        "event_type": "web_page_close",
        "issuer": "page_event_receiver",
        "nonce": "page-close-nonce-0001",
        "observed_at": (now - timedelta(seconds=4)).isoformat(),
        "sequence": 1,
        "payload": {"closed": True, "source": "browser_pagehide"},
    })
    page_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": "page-observer-nonce-01",
        "observed_at": (now - timedelta(seconds=3)).isoformat(),
        "sequence": 2,
        "payload": {
            "subject_nonce": page["nonce"],
            "scheduler_continues": True,
            "observation_source": "postgresql_scheduler_state",
            "database_read_only": True,
            "cloud_cycles_before": 2,
            "cloud_cycles_after": 3,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        },
    })
    electron = _sign({
        **common,
        "event_type": "electron_exit",
        "issuer": "windows_runner",
        "nonce": "electron-exit-nonce-01",
        "observed_at": (now - timedelta(seconds=2)).isoformat(),
        "sequence": 3,
        "payload": {"exited": True, "process_id": 4201},
    })
    electron_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": "electron-observer-0001",
        "observed_at": (now - timedelta(seconds=1)).isoformat(),
        "sequence": 4,
        "payload": {
            "subject_nonce": electron["nonce"],
            "scheduler_continues": True,
            "observation_source": "postgresql_scheduler_state",
            "database_read_only": True,
            "cloud_cycles_before": 3,
            "cloud_cycles_after": 4,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        },
    })
    return {"events": [page, page_observer, electron, electron_observer]}


def test_signed_evidence_events_bind_release_store_time_order_and_observer(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)

    result = verify_acceptance_event_bundle(
        _bundle(now),
        expected_scope=_scope(),
        now=now,
        nonce_ledger=tmp_path / "seen-nonces.json",
    )

    assert result["web_page_close"] == {
        "closed": True,
        "cloud_cycles_before": 2,
        "cloud_cycles_after": 3,
        "eligible_store_ids": [7],
        "collected_store_ids_after": [7],
        "observation_source": "postgresql_scheduler_state",
        "database_read_only": True,
    }
    assert result["electron_exit"]["exited"] is True
    assert result["electron_exit"]["process_id"] == 4201
    assert result["electron_exit"]["cloud_cycles_after"] == 4
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert result["evidence_trust_manifest_id"] == "r297-evidence-trust-test-v1"
    assert result["evidence_trust_manifest_sha256"] == "0eac4b3fc49f913f33762dbedbe41916c3ef50eb1128211d7d93281c78902fed"
    ledger = json.loads((tmp_path / "seen-nonces.json").read_text())
    assert len(ledger) == 4
    assert all(set(entry) == {
        "namespace", "tenant_id", "company_id", "store_id", "platform",
        "release_sha", "event_type", "key_id", "nonce",
    } for entry in ledger)

    with pytest.raises(ValueError, match="replayed evidence nonce"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=_scope(), now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )


def test_signed_evidence_events_reject_concurrent_replay(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger = tmp_path / "seen-nonces.json"

    def verify():
        try:
            verify_acceptance_event_bundle(
                _bundle(now), expected_scope=_scope(), now=now, nonce_ledger=ledger,
            )
            return "accepted"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: verify(), range(2)))

    assert sorted(results) == ["accepted", "replayed evidence nonce"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("namespace", ""),
        ("tenant_id", True),
        ("company_id", "company with spaces"),
        ("store_id", True),
        ("platform", "JD"),
    ],
)
def test_signed_evidence_events_reject_invalid_expected_scope(field, value, tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    scope[field] = value

    with pytest.raises(ValueError, match="invalid expected evidence binding"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=scope, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )


def test_signed_evidence_events_reject_boolean_scope_alias(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    scope["tenant_id"] = 1
    bundle = _bundle(now)
    for event in bundle["events"]:
        event["tenant_id"] = True

    with pytest.raises(ValueError, match="tenant_id mismatch"):
        verify_acceptance_event_bundle(
            bundle, expected_scope=scope, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )


def test_process_evidence_rejects_caller_supplied_trust_anchor(monkeypatch, tmp_path):
    from ops import r297_process_acceptance

    output = tmp_path / "must-not-exist"
    bundle = tmp_path / "events.json"
    keys = tmp_path / "attacker-keys.json"
    bundle.write_text("{}")
    keys.write_text("{}")
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(sys, "argv", [
        "r297_process_acceptance.py", str(output), "--runtime-image", "unused",
        "--signed-event-bundle", str(bundle), "--event-public-keys", str(keys),
    ])

    with pytest.raises(SystemExit):
        r297_process_acceptance.main()
    assert not output.exists()


def test_process_evidence_requires_real_signed_event_inputs(monkeypatch, tmp_path):
    from ops import r297_process_acceptance

    output = tmp_path / "must-not-exist"
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        sys,
        "argv",
        ["r297_process_acceptance.py", str(output), "--runtime-image", "unused"],
    )

    with pytest.raises(SystemExit):
        r297_process_acceptance.main()
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda bundle, now: bundle["events"][0].update(release_sha="0" * 40), "release_sha mismatch"),
        (lambda bundle, now: bundle["events"][0].update(namespace="other"), "namespace mismatch"),
        (lambda bundle, now: bundle["events"][0].update(tenant_id="other"), "tenant_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(company_id="other"), "company_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(store_id=8), "store_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(platform="other"), "platform mismatch"),
        (lambda bundle, now: bundle["events"][0].update(sequence=True), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0].update(observed_at=(now - timedelta(minutes=6)).isoformat()), "expired evidence event"),
        (lambda bundle, now: bundle["events"][0].update(observed_at=(now + timedelta(minutes=1)).isoformat()), "future evidence event"),
        (lambda bundle, now: bundle["events"][1].update(sequence=1), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0]["payload"].update(scheduler_continues=True), "client scheduler claim forbidden"),
        (lambda bundle, now: bundle["events"][1].update(signature=bundle["events"][0]["signature"]), "invalid evidence signature"),
    ],
)
def test_signed_evidence_events_fail_closed(mutation, error, tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    bundle = deepcopy(_bundle(now))
    mutation(bundle, now)

    with pytest.raises(ValueError, match=error):
        verify_acceptance_event_bundle(
            bundle, expected_scope=_scope(), now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )
