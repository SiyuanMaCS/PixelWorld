"""Record a frozen checkout and actual native-run profile without model calls.

The public report contains hashes and normalized runtime settings, never prompt
text, API credentials, private provider URLs, or the native raw conversation.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalize_command(command):
    values=list(command)
    for i,value in enumerate(values):
        if i and values[i-1] in ('-C','--image','-i','-o'):
            values[i]={'-C':'<CASE_WORKSPACE>','--image':'<FIRST_FRAME>',
                       '-i':'<FIRST_FRAME>','-o':'<FINAL_TEXT>'}[values[i-1]]
        elif '.base_url=' in value:
            values[i]=value.split('=',1)[0]+'="<RESPONSES_BASE_URL>"'
        elif value.startswith('model_catalog_json='):
            values[i]='model_catalog_json="<MODEL_CATALOG>"'
    return values


def profile(code, sample, configs, protocol, proxy=None):
    manifest=json.loads((sample/'run_manifest.json').read_text())
    if manifest.get('generation_contract')!='minimal-v2':
        raise ValueError('Profile sample is not native v2')
    if manifest.get('task_prompt_file')!='task_prompt.txt':
        raise ValueError('Missing preserved task text identity')
    expected_task=(code/f'pixelworld/assets/TASK_{manifest["track"].upper().replace("-","_")}.md').read_text()
    expected_task+='\nAim for high-quality output while considering efficiency.\n'
    if (sample/'task_prompt.txt').read_text()!=expected_task:
        raise ValueError('Sample task differs from the frozen native task; do not fingerprint an RSI override as baseline')
    fingerprints={}
    for name,expected in protocol['generation_files_sha256'].items():
        actual=digest(code/name)
        if actual!=expected:raise ValueError('Frozen file mismatch: '+name)
        fingerprints[name]=actual
    snapshot=sample/'input_snapshot'
    actual_inputs={p.name:digest(p) for p in snapshot.iterdir() if p.is_file()}
    if actual_inputs!=manifest['initial_input_hashes']:
        raise ValueError('Native sample immutable input hashes disagree')
    packages={}
    for name in ('numpy','Pillow','opencv-python','opencv-python-headless','scipy'):
        try:packages[name]=metadata.version(name)
        except metadata.PackageNotFoundError:pass
    codex=shutil.which('codex')
    command=manifest['command'];settings={}
    for i,x in enumerate(command[:-1]):
        if x=='-c' and '=' in command[i+1]:
            name,value=command[i+1].split('=',1);settings[name]=value
    disabled={command[i+1] for i,x in enumerate(command[:-1]) if x=='--disable'}
    if ('--ignore-user-config' not in command or '--ignore-rules' not in command
            or settings.get('sandbox_workspace_write.network_access')!='false'
            or settings.get('project_doc_max_bytes')!='0' or settings.get('skills.bundled.enabled')!='false'
            or not {'plugins','memories','hooks','multi_agent'}<=disabled):
        raise ValueError('Sample does not prove the recorded native isolation settings')
    home=Path(manifest['isolated_codex_home'])
    if home.parent.resolve()!=sample.resolve():raise ValueError('Codex home is not isolated per run')
    result={'schema':'pixelworld-native-baseline-profile-v1',
            'baseline_id':protocol['baseline_id'],'code_commit':protocol['code_commit'],
            'generation_files_sha256':fingerprints,
            'native_cli':{'recorded_version':manifest['codex_version'],
                          'currently_available_version':subprocess.check_output([codex,'--version'],text=True).strip() if codex else None,
                          'entrypoint_sha256':digest(Path(codex)) if codex else None,
                          'normalized_command':normalize_command(manifest['command'])},
            'generation_runtime':{'python':platform.python_version(),'platform':platform.system(),
                                  'machine':platform.machine(),'packages':packages},
            'sample':{'case_id':manifest['case_id'],'model_key':manifest['model_key'],'track':manifest['track'],
                      'task_prompt_sha256':digest(sample/'task_prompt.txt'),
                      'rules_sha256':actual_inputs['GENERATION_RULES.md'],
                      'initial_files':sorted(actual_inputs),
                      'support_files_sha256':{name:actual_inputs[name] for name in ('artifact_io.py','player_template.html')},
                      'media_contract':manifest['media_contract']},
            'configuration_fingerprints':[],
            'isolation':{'fresh_codex_home':True,'inherited_project_instructions':False,
                         'bundled_skills':False,'plugins_and_memory':False,'tool_network_access':False,
                         'filesystem_sandbox':'workspace-write; successful outside-task reads also audited',
                         'os_read_access_confined_to_workspace':False},
            'limitations':['OS paths and runtime date descriptions can vary between runs; raw traces preserve them.',
                           'The public normalized command is a recipe, not the hash of a private full command.',
                           'Version and entrypoint hash record this installation; user-owned installations/platforms must be recorded separately.',
                           'Package list covers common local image/math packages, not every importable system package.']}
    for config_path in configs:
        config=json.loads(config_path.read_text())
        inventory=Path(config['inputs_root']).parent/(Path(config['inputs_root']).name+'_manifest.json')
        sanitized={k:config[k] for k in ('protocol','max_concurrency','max_per_config','max_attempts','output_token_budget')}
        sanitized['models']=[{'key':m['key'],'model':m['model'],'tracks':m['tracks'],
                             'cli_backend':m.get('cli_backend','codex'),'reasoning_effort':m.get('reasoning_effort','high'),
                             'provider_type':m.get('provider',{}).get('type','builtin')} for m in config['models']]
        sanitized['case_count']=len(config.get('case_ids') or json.loads(inventory.read_text())['cases'])
        result['configuration_fingerprints'].append({'benchmark':Path(config['inputs_root']).name,
                'private_config_sha256':digest(config_path),'public_settings':sanitized,
                'prepared_inventory_sha256':digest(inventory) if inventory.exists() else None})
    # The first completed API request is linked by its archived response ID.
    if proxy:
        response=None
        for line in (sample/'logs/full_rollout.jsonl').open():
            event=json.loads(line)
            if event.get('type')=='token_usage_record':
                candidate=event.get('payload',{}).get('response_id')
                if candidate and re.fullmatch(r'resp_[0-9a-f]{32}',candidate):response=candidate;break
        if response:
            path=proxy/(response+'.input.json')
            if path.exists():
                request=json.loads(path.read_text())
                system={'instructions':request.get('instructions'),
                        'messages':[x for x in request.get('input',[]) if x.get('role') in ('system','developer')]}
                tools=request.get('tools',[])
                result['sample']['native_api_fingerprints']={
                    'private_request_sha256':digest(path),
                    'compiled_system_sha256':hashlib.sha256(json.dumps(system,sort_keys=True).encode()).hexdigest(),
                    'tool_schema_sha256':hashlib.sha256(json.dumps(tools,sort_keys=True).encode()).hexdigest(),
                    'top_level_tool_types':[x.get('type') for x in tools],
                    'top_level_tool_names':[x.get('name') for x in tools]}
                converted=proxy/(response+'.native.json')
                if converted.exists():
                    native=json.loads(converted.read_text())
                    systems=[x for x in native.get('messages',[]) if x.get('role')=='system']
                    result['sample']['native_api_fingerprints'].update({
                        'private_converted_request_sha256':digest(converted),
                        'converted_system_messages_sha256':hashlib.sha256(json.dumps(systems,sort_keys=True).encode()).hexdigest(),
                        'converted_tool_schema_sha256':hashlib.sha256(json.dumps(native.get('tools',[]),sort_keys=True).encode()).hexdigest(),
                        'scope':'Actual archived client request and converted native payload; provider-internal prompt additions are not observable.'})
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--code-root',type=Path,required=True)
    p.add_argument('--sample-run',type=Path,required=True);p.add_argument('--config',type=Path,action='append',required=True)
    p.add_argument('--protocol',type=Path,default=Path('baselines/native_v2_100k/protocol.json'))
    p.add_argument('--proxy-log-root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=profile(a.code_root,a.sample_run,a.config,json.loads(a.protocol.read_text()),a.proxy_log_root)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'profile':str(a.output),'frozen_files_verified':len(result['generation_files_sha256']),
                      'native_api_fingerprints_recorded':'native_api_fingerprints' in result['sample']}))


if __name__=='__main__':main()
