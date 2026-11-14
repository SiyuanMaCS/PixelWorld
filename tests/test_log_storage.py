import json
import time
from pathlib import Path

import pytest

from pixelworld.log_storage import SpoolBudget, StorageBackpressure
from pixelworld.runner import _provider_infra_failure
from pixelworld.retries import infrastructure_failure
from tools.spool_api_logs import copy_record, prune_record


def test_admission_reserves_capacity_across_concurrent_requests(tmp_path):
    budget=SpoolBudget(tmp_path,150*1024**2)
    budget.acquire('one',100,timeout=0)
    budget.acquire('two',100,timeout=0)
    with pytest.raises(StorageBackpressure):budget.acquire('three',100,timeout=0)
    budget.release('one')
    budget.acquire('three',100,timeout=0)


def test_exact_logged_bytes_and_oversized_record_is_rejected(tmp_path):
    budget=SpoolBudget(tmp_path,100*1024**2)
    budget.acquire('one',100,timeout=0)
    value=b'{"image":"test","text":"exact"}'
    budget.write('one','resp_one.input.json',value)
    assert (tmp_path/'resp_one.input.json').read_bytes()==value
    budget.reservations['one']=3
    with pytest.raises(StorageBackpressure):budget.write('one','too_big.json',b'1234')
    assert not (tmp_path/'too_big.json').exists()


def test_verified_compressed_archive_is_readable_and_reclaimed(tmp_path):
    import gzip
    spool=tmp_path/'spool';spool.mkdir()
    source=spool/'resp_abcd.input.json';source.write_bytes(b'{"all":"original bytes"}')
    archive=tmp_path/'archive';receipt=copy_record(source,archive,compress=True)
    assert gzip.open(archive/receipt['archive'],'rb').read()==source.read_bytes()
    assert receipt['readback_verified']
    assert prune_record(source,receipt,min_age=0)
    assert not source.exists()
    assert (archive/receipt['archive']).is_file()


def test_active_or_changed_records_are_never_pruned(tmp_path):
    source=tmp_path/'resp_abcd.input.json';source.write_bytes(b'original')
    receipt=copy_record(source,tmp_path/'archive',compress=True)
    marker=tmp_path/'resp_abcd.active.json';marker.write_text('{}')
    assert not prune_record(source,receipt,min_age=0)
    marker.unlink();source.write_bytes(b'new version')
    assert not prune_record(source,receipt,min_age=0)


def test_disk_exhaustion_and_backpressure_do_not_consume_model_attempts(tmp_path):
    events=tmp_path/'events.jsonl'
    for message in ['502 Bad Gateway: [Errno 28] No space left on device',
                    '503 storage_backpressure: durable log buffer full']:
        events.write_text(json.dumps({'type':'error','message':message}))
        reason=_provider_infra_failure(events)
        assert reason=='storage_infrastructure_failure'
        assert infrastructure_failure({'stop_reason':reason})
        assert not infrastructure_failure({'stop_reason':'output_token_budget_exhausted'})
