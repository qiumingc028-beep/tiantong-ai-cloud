from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys

import pytest

from ops.r297_evidence_events import trusted_keys_sha256, verify_acceptance_event_bundle
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


def _integer(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")


def _keys() -> dict:
    return {
        issuer: {"key_id": f"r297-{issuer}-test", "n": values[0], "e": "AQAB"}
        for issuer, values in _PRIVATE_KEYS.items()
    }


def _sign(event: dict) -> dict:
    modulus_b64, private_b64 = _PRIVATE_KEYS[event["issuer"]]
    event = {**event, "key_id": f"r297-{event['issuer']}-test"}
    canonical = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(canonical).digest()
    encoded = b"\x00\x01" + b"\xff" * (256 - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), _integer(private_b64), _integer(modulus_b64)).to_bytes(256, "big")
    return {**event, "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode()}


def _bundle(now: datetime) -> dict:
    release = "9b466ac80122e35893cbaa408735136acc88331a"
    common = {"release_sha": release, "store_id": 7}
    page = _sign({
        **common,
        "event_type": "web_page_close",
        "issuer": "page_event_receiver",
        "nonce": "page-close-nonce-0001",
        "occurred_at": (now - timedelta(seconds=4)).isoformat(),
        "sequence": 1,
        "payload": {"closed": True, "source": "browser_pagehide"},
    })
    page_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": "page-observer-nonce-01",
        "occurred_at": (now - timedelta(seconds=3)).isoformat(),
        "sequence": 2,
        "payload": {
            "subject_nonce": page["nonce"],
            "scheduler_continues": True,
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
        "occurred_at": (now - timedelta(seconds=2)).isoformat(),
        "sequence": 3,
        "payload": {"exited": True, "process_id": 4201},
    })
    electron_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": "electron-observer-0001",
        "occurred_at": (now - timedelta(seconds=1)).isoformat(),
        "sequence": 4,
        "payload": {
            "subject_nonce": electron["nonce"],
            "scheduler_continues": True,
            "cloud_cycles_before": 3,
            "cloud_cycles_after": 4,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        },
    })
    return {"events": [page, page_observer, electron, electron_observer]}


def test_signed_evidence_events_bind_release_store_time_order_and_observer(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    keys = _keys()

    result = verify_acceptance_event_bundle(
        _bundle(now),
        keys,
        expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
        expected_store_id=7,
        now=now,
        nonce_ledger=tmp_path / "seen-nonces.json",
        expected_public_keys_sha256=trusted_keys_sha256(keys),
    )

    assert result["web_page_close"] == {
        "closed": True,
        "cloud_cycles_before": 2,
        "cloud_cycles_after": 3,
        "eligible_store_ids": [7],
        "collected_store_ids_after": [7],
    }
    assert result["electron_exit"]["exited"] is True
    assert result["electron_exit"]["process_id"] == 4201
    assert result["electron_exit"]["cloud_cycles_after"] == 4
    assert result["authenticated_observer"]["verified_subject_count"] == 2

    with pytest.raises(ValueError, match="replayed evidence nonce"):
        verify_acceptance_event_bundle(
            _bundle(now), keys,
            expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
            expected_store_id=7, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
            expected_public_keys_sha256=trusted_keys_sha256(keys),
        )


def test_signed_evidence_events_reject_concurrent_replay(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    keys = _keys()
    ledger = tmp_path / "seen-nonces.json"

    def verify():
        try:
            verify_acceptance_event_bundle(
                _bundle(now), keys,
                expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
                expected_store_id=7, now=now, nonce_ledger=ledger,
                expected_public_keys_sha256=trusted_keys_sha256(keys),
            )
            return "accepted"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: verify(), range(2)))

    assert sorted(results) == ["accepted", "replayed evidence nonce"]


def test_signed_evidence_events_require_pinned_isolated_issuer_keys(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    keys = _keys()
    with pytest.raises(ValueError, match="trusted key digest mismatch"):
        verify_acceptance_event_bundle(
            _bundle(now), keys,
            expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
            expected_store_id=7, now=now, nonce_ledger=tmp_path / "seen-nonces.json",
            expected_public_keys_sha256="0" * 64,
        )

    keys["windows_runner"] = {**keys["windows_runner"], "n": keys["page_event_receiver"]["n"]}
    with pytest.raises(ValueError, match="evidence issuer keys not isolated"):
        verify_acceptance_event_bundle(
            _bundle(now), keys,
            expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
            expected_store_id=7, now=now, nonce_ledger=tmp_path / "seen-nonces.json",
            expected_public_keys_sha256=trusted_keys_sha256(keys),
        )


def test_process_evidence_requires_real_signed_event_inputs(monkeypatch, tmp_path):
    from ops import r297_process_acceptance

    output = tmp_path / "must-not-exist"
    monkeypatch.setenv("APP_ENV", "test")
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
        (lambda bundle, now: bundle["events"][0].update(release_sha="0" * 40), "release SHA mismatch"),
        (lambda bundle, now: bundle["events"][0].update(store_id=8), "store scope mismatch"),
        (lambda bundle, now: bundle["events"][0].update(sequence=True), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0].update(occurred_at=(now - timedelta(minutes=6)).isoformat()), "expired evidence event"),
        (lambda bundle, now: bundle["events"][1].update(sequence=1), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0]["payload"].update(scheduler_continues=True), "client scheduler claim forbidden"),
        (lambda bundle, now: bundle["events"][1].update(signature=bundle["events"][0]["signature"]), "invalid evidence signature"),
    ],
)
def test_signed_evidence_events_fail_closed(mutation, error, tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    bundle = deepcopy(_bundle(now))
    mutation(bundle, now)
    keys = _keys()

    with pytest.raises(ValueError, match=error):
        verify_acceptance_event_bundle(
            bundle, keys,
            expected_release_sha="9b466ac80122e35893cbaa408735136acc88331a",
            expected_store_id=7, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
            expected_public_keys_sha256=trusted_keys_sha256(keys),
        )
