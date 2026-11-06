import json
from pathlib import Path
import pytest
from PIL import Image
from pixelworld.config import load_config
from pixelworld.runner import run_case


def setup(tmp_path):
    source=tmp_path/'inputs/0001';source.mkdir(parents=True)
    Image.new('RGB',(256,144),'white').save(source/'first_frame.png')
    (source/'prompt.txt').write_text('A ball falls.')
    (source/'generate.py').write_text('# provided candidate program')
    task=tmp_path/'task.txt';task.write_text('Repair the supplied candidate.')
    rules=tmp_path/'rules.md';rules.write_text('Use supplied candidate and initial input only.')
    config=tmp_path/'config.json';config.write_text(json.dumps({'protocol':'pixelworld-v2','inputs_root':'inputs','runs_root':'runs','models':[{'key':'m','model':'local','tracks':['vision-agent']}]}))
    return load_config(config),task,rules


def test_explicit_experimental_inputs_are_frozen_and_auditable(tmp_path):
    config,task,rules=setup(tmp_path)
    result=run_case(config,'m','vision-agent','0001',codex_binary='/bin/true',dry_run=True,
                    task_file=task,rules_file=rules,extra_inputs=('generate.py',))
    workspace=Path(result['workspace'])
    assert (workspace/'generate.py').read_text()=='# provided candidate program'
    assert (workspace/'GENERATION_RULES.md').read_text()==rules.read_text()
    assert (workspace.parent/'task_prompt.txt').read_text()==task.read_text()
    assert result['extra_input_files']==['generate.py']


def test_experimental_input_cannot_escape_prepared_case(tmp_path):
    config,task,rules=setup(tmp_path)
    with pytest.raises(ValueError):run_case(config,'m','vision-agent','0001',dry_run=True,extra_inputs=('../prompt.txt',))
