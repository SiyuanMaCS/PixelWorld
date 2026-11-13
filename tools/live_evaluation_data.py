"""Export sanitized full-cohort scores and evaluation stages for live Pages."""
import json
import math
from pathlib import Path
from datetime import datetime, timezone

from pixelworld.constants import PHYSICS_IQ_COMMIT, PHYSICS_IQ_DATASET_REVISION
from pixelworld import pcve
from pixelworld.smoke_web import clean
from tools.evaluate_robojudge_shared50 import CODE_REVISION, CHECKPOINT_REVISION, DATASET_REVISION, TASKS_SHA256

COHORTS = {
    'physics_iq_720p24fps':('Physics-IQ Verified · 720p24fps','physics_720p24fps_full_scheduler',198),
    'physics_iq_4k24fps':('Physics-IQ Verified · 4K24fps','physics_4k24fps_full_scheduler',198),
    'physics_iq':('Physics-IQ Verified','physics_full_scheduler',198),
    'physics_iq_gpt_native_v2':('Physics-IQ Verified','physics_gpt_native_v2_full_scheduler',198),
    'physics_iq_seed21_native_v2':('Physics-IQ Verified','physics_seed21_native_v2_full_scheduler',198),
    'physics_iq_512w24fps_gpt_native':('Physics-IQ Verified · 512w24fps','physics_highres_512w24fps_full_scheduler',198),
    'robojudge':('RoboJudge shared-50','robojudge_full_baseline100k',50),
    'robojudge_seed21_native_v2':('RoboJudge shared-50','robojudge_seed21_native_v2_full',50),
    'pcve_smoke':('PCVE-RigidBench','pcve_full_scheduler',129),
}


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)


def note(value):
    if isinstance(value,dict):
        value='; '.join(str(value[k]) for k in ('phase','blocker','missing_relative_path','missing','detail','reason') if value.get(k))
    return clean(str(value or ''))[:1200]


def live_commands():
    values=[]
    if not Path('/proc').is_dir():return values
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if (proc/'stat').read_text().rsplit(') ',1)[1].split()[0]=='Z':continue
            argv=[v.decode(errors='replace') for v in (proc/'cmdline').read_bytes().split(b'\0') if v]
            values.append((int(proc.name),argv))
        except OSError:continue
    return values


def evaluator_active(cohort, commands):
    path=str(cohort.resolve())
    for _,argv in commands:
        identity=('physiq.run_physics_iq' in argv or
                  any(Path(v).name in ('evaluate_pcve_full.py','evaluate_robojudge_shared50.py') for v in argv))
        if identity and any(v.startswith(path) for v in argv):return True
        if argv and Path(argv[0]).name=='ssh' and any(path in v and 'official_driver.py' in v for v in argv):return True
    return False


def physics_score(score, model, track):
    if not (score.get('inputs')==198 and score.get('upstream_commit')==PHYSICS_IQ_COMMIT
            and score.get('dataset_revision')==PHYSICS_IQ_DATASET_REVISION
            and score.get('model_key')==model and score.get('track')==track
            and finite(score.get('verified_score')) and finite(score.get('original_formula_score'))):
        return None
    return {'metrics':{'Verified':100*score['verified_score'],'Original formula':100*score['original_formula_score']},
            'units':'/100','scope':198,'prompt_setting':score.get('prompt_setting'),
            'independent_runs':score.get('independent_runs',1),
            'fps':score.get('fps'),'frames':score.get('frames'),'resolution':score.get('resolution'),
            'completed_utc':score.get('completed_utc'),'source_revision':score['upstream_commit'],
            'dataset_revision':score['dataset_revision'],'metrics_sha256':score.get('official_metrics_sha256')}


def robo_score(summary, plan, execution, model, track):
    rows=summary.get('items') or []
    expected={f'common50_{i:04d}' for i in range(50)}
    if not (summary.get('complete_shared50') is True and summary.get('valid_paired_count')==50
            and plan.get('scope',{}).get('complete_shared50') is True
            and plan.get('scope',{}).get('prepared_count')==50
            and not any(plan.get('scope',{}).get(k) for k in ('missing','failed','duplicates'))
            and plan.get('model')==model and plan.get('track')==track
            and plan.get('code_revision')==CODE_REVISION and plan.get('checkpoint_revision')==CHECKPOINT_REVISION
            and plan.get('dataset_revision')==DATASET_REVISION and plan.get('tasks_sha256')==TASKS_SHA256
            and execution.get('returncode')==0 and len(rows)==50
            and {r.get('case_id') for r in rows}==expected):
        return None
    if any(not finite(r.get(k)) or not 1<=r[k]<=5 for r in rows for k in ('PA','IA')):
        return None
    means={k:sum(r[k] for r in rows)/50 for k in ('PA','IA')}
    means['mean']=(means['PA']+means['IA'])/2
    reported=summary.get('shared50_means') or {}
    if any(not finite(reported.get(k)) or abs(reported[k]-v)>1e-9 for k,v in means.items()):
        return None
    return {'metrics':{'PA':means['PA'],'IA':means['IA'],'Mean':means['mean']},'units':'1–5','scope':50,
            'source_revision':CODE_REVISION,'checkpoint_revision':CHECKPOINT_REVISION,
            'dataset_revision':DATASET_REVISION,'table8_comparability_verified':False,
            'case_scores':{r['case_id']:{'PA':r['PA'],'IA':r['IA'],'Mean':(r['PA']+r['IA'])/2} for r in rows}}


def pcve_score(summary, model, track):
    scores=summary.get('scores') or {};overall=scores.get('overall') or {}
    fields={'PES':'pes','TE px':'traj_px','Mask IoU':'mask_iou','PSNR':'psnr','SSIM':'ssim','LPIPS':'lpips','CLIP':'clip_sim'}
    if not (summary.get('complete_official129') is True and summary.get('case_count')==129
            and summary.get('source_revision')==pcve.EVALUATOR_REVISION
            and summary.get('dataset_revision')==pcve.DATASET_REVISION
            and summary.get('model')==model and summary.get('track')==track
            and all(finite(overall.get(k)) for k in fields.values()) and finite(scores.get('fvd'))):
        return None
    return {'metrics':{**{name:overall[key] for name,key in fields.items()},'FVD':scores['fvd']},
            'units':'original metrics','scope':129,'fps':summary.get('fps'),
            'frames':summary.get('frames'),'resolution':summary.get('resolution'),
            'completed_utc':summary.get('completed_utc'),'source_revision':summary['source_revision'],
            'dataset_revision':summary['dataset_revision'],'metrics_sha256':summary.get('official_metrics_sha256')}


def collect(run_root: Path):
    result={'updated_utc':datetime.now(timezone.utc).isoformat(),'cohorts':[]}
    commands=live_commands()
    for suite,(benchmark,folder,expected) in COHORTS.items():
        generation=read(run_root/'generations'/suite/'status.json')
        scheduler=read(run_root/'evaluation'/folder/'scheduler.json')
        entries=scheduler.get('cohorts') or scheduler.get('done') or {}
        groups=generation.get('groups') or {}
        for key in sorted(set(groups)|set(entries)|set(scheduler.get('blocked') or {})):
            model,track=key.split('/',1)
            if model=='gemini38-flash':continue
            group=groups.get(key) or {};counts=group.get('counts') or {};entry=entries.get(key) or {}
            cohort=run_root/'evaluation'/folder/model/track
            execution=read(cohort/'execution.json')
            active=evaluator_active(cohort,commands)
            blocked=(scheduler.get('blocked') or {}).get(key) or {}
            phase=blocked.get('phase') or entry.get('phase') or 'waiting_for_generation'
            blocker=blocked or entry.get('blocker') or entry.get('error')
            if active and execution.get('phase')=='official_evaluation' and phase in ('adapter_evaluation','failed'):
                phase='official_evaluation'
            if phase=='failed':phase='waiting_for_evaluation_retry'
            row={'suite':suite,'benchmark':benchmark,'model_key':model,'track':track,
                 'expected':expected,'accepted':counts.get('complete',0),'generation_counts':counts,
                 'phase':phase,'blocker':note(blocker),'scheduler_updated_utc':scheduler.get('updated_utc'),
                 'full_scope_scored':False,'score':None,'evaluator_active':active}
            if suite.startswith('physics_iq'):
                score=physics_score(read(cohort/'scores.json'),model,track)
            elif suite.startswith('robojudge'):
                score=robo_score(read(cohort/'summary.json'),read(cohort/'plan.json'),execution,model,track)
            else:score=pcve_score(read(cohort/'summary.json'),model,track)
            if score and row['accepted']==expected:
                row.update(score=score,full_scope_scored=True,phase='complete',blocker='')
            elif score:
                row.update(phase='blocked_current_generation_mismatch',blocker='Scored scope disagrees with current validated generation inventory')
            elif phase=='complete' or entry.get('phase')=='full_shared50_scored':
                row.update(phase='blocked_score_provenance',blocker='Full score metadata or original task identities did not pass verification')
            elif active and row['accepted']==expected:
                row.update(phase='official_evaluation',blocker='')
            elif phase in ('official_evaluation','official_full_evaluation','adapter_evaluation') and not active:
                watcher_alive=any(pid==scheduler.get('pid') and any(Path(v).name.startswith('watch_') for v in argv)
                                  for pid,argv in commands)
                row.update(phase='preparing_evaluation' if watcher_alive else 'stale_evaluation')
                if not watcher_alive:row['blocker']='Recorded evaluator stage has no matching live process'
            elif row['accepted']==expected and phase=='waiting_for_generation':
                row['phase']='waiting_for_evaluator'
            elif not counts.get('running',0) and not counts.get('pending',0) and row['accepted']<expected and counts.get('exhausted',0):
                row.update(phase='incomplete_generation',blocker='Full official scope is incomplete; no missing-video score imputation')
            result['cohorts'].append(row)
    return result
