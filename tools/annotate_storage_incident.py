"""Preserve and exempt positively recorded storage infrastructure failures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pixelworld.util import atomic_json


def annotate(path):
    manifest=json.loads(path.read_text())
    if manifest.get('status')!='failed' or manifest.get('stop_reason')=='output_token_budget_exhausted':return None
    events=path.parent/'logs/events.jsonl'
    text=events.read_text(errors='replace') if events.exists() else ''
    if 'No space left on device' not in text and 'storage_backpressure:' not in text:return None
    original=path.parent/'logs/storage_incident_original_manifest.json'
    if not original.exists():atomic_json(original,manifest)
    manifest.setdefault('validation',{})['infra_error']='storage_infrastructure_failure'
    manifest['storage_incident_audit']={'original_manifest':'logs/storage_incident_original_manifest.json',
                                     'evidence':'logs/events.jsonl','model_attempt_exempt':True}
    atomic_json(path,manifest)
    return {'case':manifest.get('case_id'),'model':manifest.get('model_key'),'track':manifest.get('track'),
            'attempt':manifest.get('attempt'),'path':str(path.parent)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',action='append',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    paths=[f for root in a.root for f in root.glob('*/*/case_*/run_manifest.json')]
    with ThreadPoolExecutor(max_workers=8) as pool:rows=[r for r in pool.map(annotate,paths) if r]
    atomic_json(a.receipt,{'positively_identified_storage_failures':len(rows),'originals_preserved':True,'items':rows})
    print(json.dumps({'storage_failure_attempts_reclassified':len(rows)}))
