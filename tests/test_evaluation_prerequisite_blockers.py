import json
from pathlib import Path
from types import SimpleNamespace

from tools import watch_generic_benchmark_evaluation as watcher


def test_reference_download_blocker_remains_retryable_and_unscored(tmp_path, monkeypatch):
    root=tmp_path/'generations';root.mkdir()
    (root/'status.json').write_text(json.dumps({'groups':{'m/text':{'counts':{'complete':2}}}}))
    config=SimpleNamespace(case_ids=['a','b'],runs_root=root,
        models=[SimpleNamespace(key='m',tracks=['text'])])
    monkeypatch.setattr(watcher,'load_config',lambda _:config)
    def failed_download(*_,**__):
        p=tmp_path/'evaluation/m/text/prerequisites.json'
        p.write_text(json.dumps({'phase':'blocked_reference_download','detail':'proxy 504',
                                'scores_computed':False}))
        return 1
    monkeypatch.setattr(watcher.subprocess,'call',failed_download)
    state=watcher.step(Path('config.json'),tmp_path/'evaluation','pcve','echo evaluator',{})
    item=state['m/text']
    assert item['phase']=='blocked_evaluation_prerequisites'
    assert item['retryable'] is True and item['official_or_adapter_score'] is False
    assert item['phase'] not in watcher.TERMINAL
