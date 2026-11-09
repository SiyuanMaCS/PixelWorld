from tools.prove_transport_accounting import proves_no_sampling


def rejection(stage='connect',disconnected=False):
    return {'native_error':{'code':3004,'model_call_chain':[{'error_stage':stage}]},
            'client_disconnected':disconnected}


def test_explicit_connect_rejection_can_close_unknown_request():
    assert proves_no_sampling(rejection(),[{'event':'metadata','data':{}},{'event':'error','data':{'code':3004}}])


def test_partial_output_usage_or_unknown_event_never_becomes_zero():
    for event in ['output','token_usage','unrecognized_payload']:
        assert not proves_no_sampling(rejection(),[{'event':event,'data':{}},{'event':'error','data':{'code':3004}}])


def test_disconnect_and_nonconnect_failure_remain_unknown():
    events=[{'event':'error','data':{'code':3004}}]
    assert not proves_no_sampling(rejection(disconnected=True),events)
    assert not proves_no_sampling(rejection(stage='generation'),events)
    assert not proves_no_sampling({'native_error':{'code':3004}},events)


def test_no_terminal_rejection_is_not_evidence_of_zero():
    assert not proves_no_sampling(rejection(),[])
    assert not proves_no_sampling(rejection(),[{'event':'metadata','data':{}}])


def test_native_progress_marker_is_control_data_not_freeform_model_text():
    error={'event':'error','data':{'code':3004}}
    assert proves_no_sampling(rejection(),[{'event':'progress_notice','data':';Processing_123_Abc'},error])
    assert not proves_no_sampling(rejection(),[{'event':'progress_notice','data':'partial generated answer'},error])
