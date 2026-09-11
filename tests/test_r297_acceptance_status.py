from datetime import datetime, timedelta, timezone

import pytest

from backend.config import get_settings
from backend.models import (
    EmployeeLog, JdSyncLog, JdWorkbenchDevice, JdWorkbenchStoreStatus,
    JdWorkbenchSyncPolicy, Store,
)


@pytest.fixture(autouse=True)
def controlled_observation(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'acceptance')
    monkeypatch.setenv('R297_CONTROLLED_CANARY', '1')
    monkeypatch.setenv('JD_SESSION_NAMESPACE', 'acceptance-tests')
    monkeypatch.setenv('DEPLOY_COMMIT', 'a' * 40)
    monkeypatch.setenv('R297_ACCEPTANCE_RUN_ID', 'r297-run-20260907-0001')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_observation_requires_owner(client, viewer_headers):
    url = '/api/jd-workbench/stores/1/acceptance-status'
    assert client.get(url).status_code in (401, 403)
    assert client.get(url, headers=viewer_headers).status_code == 403


@pytest.mark.parametrize('environment', ['production', 'development', ''])
def test_observation_is_disabled_outside_isolated_acceptance(client, owner_headers, monkeypatch, environment):
    monkeypatch.setenv('APP_ENV', environment)
    assert client.get('/api/jd-workbench/stores/1/acceptance-status', headers=owner_headers).status_code == 404


def test_observation_missing_release_fails_closed(client, owner_headers, monkeypatch):
    monkeypatch.delenv('DEPLOY_COMMIT')
    assert client.get('/api/jd-workbench/stores/1/acceptance-status', headers=owner_headers).status_code == 503


def test_observation_counts_only_scoped_successful_cloud_windows(client, owner_headers, test_db):
    now = datetime.now(timezone.utc)
    with test_db() as db:
        store = db.get(Store, 1)
        other = Store(tenant_id=store.tenant_id, company_id=store.company_id, platform='jd',
                      store_code='observation-other', store_name='Other')
        db.add(other)
        db.flush()
        db.add(JdWorkbenchSyncPolicy(
            tenant_id=store.tenant_id, company_id=store.company_id, store_id=store.id,
            enabled=True, interval_seconds=300,
        ))
        db.add(JdWorkbenchDevice(
            device_id='acceptance-device', token_hash='f' * 64, public_key_n='n', public_key_e=65537,
            tenant_id=store.tenant_id, company_id=store.company_id, user_id=1,
            device_name='Acceptance', client_version='test', expires_at=now + timedelta(hours=1),
        ))
        db.flush()
        db.add(JdWorkbenchStoreStatus(
            device_id='acceptance-device', store_id=store.id, status='ONLINE',
            next_sync_at=now + timedelta(seconds=90),
        ))
        rows = []
        for index, (target, status, source, window) in enumerate([
            (store, 'success', 'cloud_scheduler', now),
            (store, 'success', 'cloud_scheduler', now),
            (store, 'failed', 'cloud_scheduler', now + timedelta(minutes=5)),
            (store, 'success', 'manual', now + timedelta(minutes=10)),
            (other, 'success', 'cloud_scheduler', now + timedelta(minutes=15)),
        ]):
            rows.append(JdSyncLog(tenant_id=target.tenant_id, company_id=target.company_id, store_id=target.id,
                                 task_id=f'window-{index}', task_type='sync_jd_smart', source=source,
                                 status=status, sync_window_started_at=window, attempt=index+1, finished_at=now))
        db.add_all(rows)
        db.commit()
        audit_count = db.query(EmployeeLog).count()
    response = client.get('/api/jd-workbench/stores/1/acceptance-status', headers=owner_headers)
    assert response.status_code == 200
    result = response.json()
    assert result['completed_cycle_count'] == 1
    assert result['interval_seconds'] == 300
    assert result['release_sha'] == 'a' * 40
    assert result['namespace'] == 'acceptance-tests'
    assert result['run_id'] == 'r297-run-20260907-0001'
    assert 0 <= result['next_sync_in_seconds'] <= 90
    assert result['latest_completed_at'] is not None
    assert result['store_id'] == 1
    assert set(result) == {'release_sha', 'run_id', 'namespace', 'tenant_id', 'company_id', 'store_id',
                           'platform', 'completed_cycle_count', 'interval_seconds',
                           'next_sync_in_seconds', 'latest_completed_at', 'observed_at'}
    with test_db() as db:
        assert db.query(JdSyncLog).count() == 5
        assert db.query(EmployeeLog).count() == audit_count
