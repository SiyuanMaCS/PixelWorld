"""Unscored schema fixtures, not video-model or judge inference."""
import json

import pytest

from tools.evaluate_worldarena_vlm_smoke import check_results,METRICS


def test_original_vlm_component_requires_one_exact_episode_and_three_metrics(tmp_path):
    path=tmp_path/'result.json'
    row={'video':'episode.mp4','error':None,'metrics':{key:{'score':3,'score_normalized':.6} for key in METRICS}}
    path.write_text(json.dumps([row]))
    assert set(check_results(path,'episode.mp4'))==METRICS
    with pytest.raises(ValueError,match='exact one'):check_results(path,'another.mp4')
    path.write_text(json.dumps([]))
    with pytest.raises(ValueError,match='exact one'):check_results(path,'episode.mp4')


@pytest.mark.parametrize('change',['missing_metric','default_zero','parse_error','normalization','boolean'])
def test_incomplete_original_vlm_output_is_not_a_passing_smoke(tmp_path,change):
    row={'video':'episode.mp4','error':None,'metrics':{key:{'score':3,'score_normalized':.6} for key in METRICS}}
    item=row['metrics']['Instruction_Following']
    if change=='missing_metric':del row['metrics']['Instruction_Following']
    elif change=='default_zero':item.update(score=0,score_normalized=0)
    elif change=='parse_error':row['error']='parse_failed'
    elif change=='normalization':item['score_normalized']=.7
    elif change=='boolean':item.update(score=True,score_normalized=.2)
    path=tmp_path/'result.json';path.write_text(json.dumps([row]))
    with pytest.raises(ValueError):check_results(path,'episode.mp4')
