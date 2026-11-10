"""Use pinned OpenVE Seed rubric/parser with an explicitly configured Seed-1.6-VL endpoint.

Only transport is adapted: videos are supplied as data URLs instead of uploading
them to the original author's private TOS bucket. No replacement judge is used.
"""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import urllib.request

from pixelworld.openve import SOURCE_REVISION, OFFICIAL_COUNT, rows
from pixelworld.util import atomic_json, sha256

RUBRICS = {'global_style':'Global_Style', 'local_change':'Local_Change',
           'background_change':'Background_Change', 'local_remove':'Local_Remove',
           'local_add':'Local_Add', 'creative_edit':'Creative_Edit',
           'camera_edit':'Camera_Edit', 'subtitle_edit':'Subtitle_Edit'}


def official_logic(source: Path):
    actual = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if actual != SOURCE_REVISION:
        raise ValueError('OpenVE evaluator checkout does not match the recorded protocol pin')
    script = source/'OpenVE-Bench/seed_benchmark.py'
    if subprocess.check_output(['git','-C',str(source),'diff','HEAD','--',str(script.relative_to(source))],text=True):
        raise ValueError('Official Seed rubric/parser has local edits')
    tree = ast.parse(script.read_text())
    prompts = {}
    parser = None
    for node in tree.body:
        if isinstance(node,ast.Assign):
            for name in node.targets:
                if isinstance(name,ast.Name) and name.id in RUBRICS.values():
                    prompts[name.id] = ast.literal_eval(node.value)
        if isinstance(node,ast.FunctionDef) and node.name=='extract_scores_and_average':
            namespace={}
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(script),'exec'),namespace)
            parser=namespace[node.name]
    if len(prompts)!=8 or parser is None:
        raise ValueError('Expected eight official rubrics and original score parser')
    return prompts,parser,sha256(script)


def judge(original: Path, edited: Path, prompt: str) -> str:
    # These env values are outside the generation sandbox and never written to traces.
    base=os.environ['OPENVE_SEED_BASE_URL'].rstrip('/')
    key=os.environ['OPENVE_SEED_API_KEY']
    model=os.environ['OPENVE_SEED_MODEL_ID']
    if os.environ.get('OPENVE_SEED_MODEL_IDENTITY')!='seed-1.6-vl':
        raise ValueError('Confirm that this deployed endpoint is Seed-1.6-VL; do not substitute a newer Seed judge')
    def video(path):
        data=base64.b64encode(path.read_bytes()).decode()
        return {'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+data,'fps':2}}
    payload={'model':model,'messages':[{'role':'system','content':prompt.strip()},
             {'role':'user','content':[video(original),video(edited)]}]}
    request=urllib.request.Request(base+'/chat/completions',data=json.dumps(payload).encode(),
                                  headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=180) as response:
        result=json.load(response)
    return result['choices'][0]['message']['content']


def evaluate(source: Path, input_csv: Path, data_root: Path, output: Path,
             check_only: bool=False) -> dict:
    prompts,parse,script_hash=official_logic(source)
    with input_csv.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);header=reader.fieldnames;submission=list(reader)
    if not header or not {'edited_type','prompt','original_video','edited_result_path'}<=set(header):
        raise ValueError('Expected the official submission CSV schema')
    official=rows(data_root/'benchmark_videos.csv')
    expected={(r['edited_type'],r['prompt'],r['original_video']) for r in official}
    scope=[(r['edited_type'],r['prompt'],r['original_video']) for r in submission]
    if len(scope)!=len(set(scope)) or any(x not in expected for x in scope):
        raise ValueError('Submission has duplicates or tasks outside the official CSV')
    pairs=[]
    for row in submission:
        relative=PurePosixPath(row['original_video'])
        original=data_root/'videos'/relative.name
        edited=Path(row['edited_result_path'])
        if not original.is_file() or not edited.is_file():
            raise FileNotFoundError('Both original and edited videos are required')
        pairs.append((row,original,edited))
    summary={'judge':'seed-1.6-vl','judge_endpoint_identity_confirmed':os.environ.get('OPENVE_SEED_MODEL_IDENTITY')=='seed-1.6-vl',
             'evaluator_revision':SOURCE_REVISION,'rubric_script_sha256':script_hash,
             'submitted':len(submission),'official_total':OFFICIAL_COUNT,
             'full_official_scope':set(scope)==expected,'scores_computed':False,
             'transport':'data-video-url,2fps; original private TOS upload replaced',
             'aggregation':'original row parser; valid row averages then mean',
             'score_caps':'specified in original judge prompts; not post-clamped by the official parser'}
    if check_only:
        return summary
    required=['OPENVE_SEED_BASE_URL','OPENVE_SEED_API_KEY','OPENVE_SEED_MODEL_ID','OPENVE_SEED_MODEL_IDENTITY']
    if any(not os.environ.get(k) for k in required) or not summary['judge_endpoint_identity_confirmed']:
        raise RuntimeError('OpenVE Seed-1.6-VL evaluator endpoint is not configured; no official scores were computed')
    output.parent.mkdir(parents=True,exist_ok=True)
    values=[];by_type={}
    with output.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=header+['results','average']);writer.writeheader()
        for index,(row,original,edited) in enumerate(pairs):
            try:
                response=judge(original,edited,prompts[RUBRICS[row['edited_type']]].replace('<edit_prompt>',row['prompt']))
                score=parse(response)
                if score is None or not 1<=score<=5:
                    raise ValueError('Original parser did not produce a valid 1-5 average')
                values.append(score);by_type.setdefault(row['edited_type'],[]).append(score)
                writer.writerow(row|{'results':response.replace('\n','\\n'),'average':score})
            except Exception as exc:
                # Do not emit API request/error contents that might contain credentials.
                writer.writerow(row|{'results':'ERROR: '+type(exc).__name__,'average':'ERROR'})
            f.flush()
            atomic_json(output.with_suffix('.progress.json'),{'processed':index+1,'scored':len(values),'total':len(pairs)})
    summary.update({'scores_computed':bool(values),'scored':len(values),
                    'all_submitted_scored':len(values)==len(submission),
                    'overall_average':round(sum(values)/len(values),2) if values else None,
                    'type_averages':{k:round(sum(v)/len(v),2) for k,v in by_type.items()},
                    'paper_comparability_ready':summary['full_official_scope'] and len(values)==OFFICIAL_COUNT})
    atomic_json(output.with_suffix('.stats.json'),summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--input-csv',type=Path,required=True)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check-only',action='store_true')
    a=p.parse_args();print(json.dumps(evaluate(a.source,a.input_csv,a.data_root,a.output,a.check_only),indent=2))


if __name__=='__main__':main()
