import json
from pathlib import Path
import pytest
from tools.spool_api_logs import cutover, copy_record, allowed


def test_cutover_preserves_old_evidence_keys_and_original_writer_path(tmp_path):
    original = tmp_path / 'bn/logs'
    original.mkdir(parents=True)
    (original / 'local.key').write_text('stable-test-key')
    (original / 'resp_old.input.json').write_text('{"old":true}')
    spool = tmp_path / 'local/spool'
    result = cutover(original, spool)
    assert original.is_symlink()
    assert (original / 'local.key').read_text() == 'stable-test-key'
    assert (Path(result['legacy']) / 'resp_old.input.json').read_text() == '{"old":true}'
    (original / 'resp_new.input.json').write_text('{"new":true}')
    assert (spool / 'resp_new.input.json').is_file()
    assert cutover(original, spool) == result


def test_archive_retains_source_and_never_archives_credentials(tmp_path):
    source = tmp_path / 'resp_abcd.events.json'
    source.write_text('{"tool":"exec_command"}')
    archive = tmp_path / 'archive'
    receipt = copy_record(source, archive)
    assert source.read_bytes() == (archive / receipt['archive']).read_bytes()
    assert '/ab/' in receipt['archive']
    assert not allowed(tmp_path / 'local.key')
    assert not allowed(tmp_path / 'cutover.json')
    assert allowed(source)


def test_failed_cutover_restores_live_path(tmp_path, monkeypatch):
    original = tmp_path / 'logs'
    original.mkdir()
    (original / 'local.key').write_text('unchanged')
    real_replace = Path.replace
    def fail_link(self, target):
        if self.name.endswith('.cutover-link'):
            raise OSError('test replacement failure')
        return real_replace(self, target)
    monkeypatch.setattr(Path, 'replace', fail_link)
    with pytest.raises(OSError):
        cutover(original, tmp_path / 'spool')
    assert original.is_dir() and not original.is_symlink()
    assert (original / 'local.key').read_text() == 'unchanged'
