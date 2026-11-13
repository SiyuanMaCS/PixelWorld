from tools.live_case_diagnostics import diagnostics,public_text


def fixture(tmp_path):
    (tmp_path/'workspace').mkdir();(tmp_path/'logs').mkdir()
    manifest={'status':'failed','exit_status':0,'validation':{
        'generate_runs':0,'frames':0,'missing_required':['generate.py','pixels.npz'],
        'completion_mode':'agent_finished'}}
    events=[{'kind':'agent_message','text':'I am mapping the three object footprints.'},
            {'kind':'turn.completed','text':''}]
    return manifest,events


def test_no_submission_reports_actual_normal_exit_and_last_model_message(tmp_path):
    manifest,events=fixture(tmp_path)
    value=diagnostics(tmp_path,manifest,{},events)
    assert value['kind']=='ended_without_submission' and value['exit_status']==0
    assert value['generate_runs']==0 and value['terminal_events']==['turn.completed']
    assert value['last_agent_message']=='I am mapping the three object footprints.'


def test_present_but_unrecognized_pixels_are_distinct_from_no_submission(tmp_path):
    manifest,events=fixture(tmp_path)
    (tmp_path/'workspace/pixels.npz').write_bytes(b'invalid saved submission')
    assert diagnostics(tmp_path,manifest,{},events)['kind']=='submitted_but_unrecognized'
    manifest['stop_reason']='output_token_budget_exhausted'
    assert diagnostics(tmp_path,manifest,{},events)['kind']=='token_budget_exhausted'


def test_infrastructure_diagnostics_preserve_reason_without_exposing_secrets(tmp_path):
    manifest,events=fixture(tmp_path);manifest['validation']['infra_error']='429 Too Many Requests'
    (tmp_path/'logs/stderr.log').write_text('Bearer sk-sensitive_value\napi_key=my_sensitive_key\n/mnt/private/credential.txt')
    value=diagnostics(tmp_path,manifest,{},events)
    assert value['kind']=='infra_failure' and value['reason']=='429 Too Many Requests'
    assert 'sk-sensitive_value' not in value['stderr_excerpt']
    assert 'my_sensitive_key' not in value['stderr_excerpt'] and '/mnt/private' not in value['stderr_excerpt']


def test_active_or_successful_cases_do_not_receive_failure_diagnoses(tmp_path):
    manifest,events=fixture(tmp_path)
    for status in ('running','complete'):
        manifest['status']=status
        assert diagnostics(tmp_path,manifest,{},events) is None
