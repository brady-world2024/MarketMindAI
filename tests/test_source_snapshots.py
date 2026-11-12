import json

import pytest

from marketmind_ai.dataflows.source_records import ResearchDataSnapshot, SourceRecord
from marketmind_ai.dataflows.source_store import SnapshotIntegrityError, SourceStore


def sample(store, **changes):
    blob = store.write_blob('SEC source body with 0 and missing null')
    payload = dict(origin_run_id='run-a', original_input='ABC', symbol='ABC', data_mode='live',
        cutoff={'requested_date': '2026-06-12', 'effective_session_date': '2026-06-12', 'cutoff_at': '2026-06-12T20:00:00+00:00'},
        resolution={'resolved_symbol': 'ABC'}, availability={'can_recommend': False},
        records=[SourceRecord(method='get_income_statement', provider='sec', symbol='ABC', data_mode='live',
            admissibility='included', content={'income': 0, 'missing': None}, raw_sha256=blob)],
        inputs={'income_statement': {'value': 'Income: 0'}})
    payload.update(changes)
    return ResearchDataSnapshot(**payload)


def test_snapshot_round_trip_is_offline_and_immutable(tmp_path, monkeypatch):
    import urllib.request
    store = SourceStore(tmp_path)
    snapshot = sample(store)
    digest = store.save(snapshot)
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Replay cannot fetch'))
    loaded = store.load(snapshot.snapshot_id)
    assert loaded.to_dict() == snapshot.to_dict()
    assert store.save(loaded) == digest
    with pytest.raises(SnapshotIntegrityError):
        store.save(snapshot.model_copy(update={'inputs': {'different': True}}))
    refreshed = sample(store)
    store.save(refreshed)
    assert refreshed.snapshot_id != snapshot.snapshot_id
    assert store.load(snapshot.snapshot_id).inputs == snapshot.inputs


@pytest.mark.parametrize('damage', ['manifest', 'blob', 'missing'])
def test_corrupt_or_missing_content_does_not_silently_recover(tmp_path, damage):
    store = SourceStore(tmp_path)
    snapshot = sample(store)
    store.save(snapshot)
    if damage == 'manifest':
        path = tmp_path / 'snapshots' / f'{snapshot.snapshot_id}.json'
        data = json.loads(path.read_text())
        data['snapshot']['symbol'] = 'OTHER'
        path.write_text(json.dumps(data))
    else:
        path = tmp_path / 'blobs' / snapshot.records[0].raw_sha256
        path.unlink() if damage == 'missing' else path.write_text('changed')
    with pytest.raises(SnapshotIntegrityError):
        store.load(snapshot.snapshot_id)


def test_unknown_versions_and_paths_fail(tmp_path):
    store = SourceStore(tmp_path)
    with pytest.raises(SnapshotIntegrityError):
        store.save(sample(store, format_version=999))
    for value in ('../private', '/tmp/secret', 'not-a-snapshot'):
        with pytest.raises(SnapshotIntegrityError):
            store.load(value)
    with pytest.raises(SnapshotIntegrityError):
        store.read_blob('../private')


def test_credentials_are_redacted_in_raw_bodies_and_manifests(tmp_path):
    store = SourceStore(tmp_path)
    digest = store.write_blob('https://source.test/?apikey=private-value\nAuthorization: Bearer private-token')
    snapshot = sample(store, inputs={'api_key': 'another-private-value'})
    store.save(snapshot)
    assert 'private-value' not in store.read_blob(digest)
    assert 'private-token' not in store.read_blob(digest)
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert b'another-private-value' not in path.read_bytes()
