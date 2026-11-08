from pixelworld.usage import preserve_completed_request_bound

def test_queue_or_transport_failure_keeps_counter_without_fabricated_total():
    usage={'status':'missing','output_tokens':None,'input_tokens':None}
    result=preserve_completed_request_bound(usage,{'reported_output_tokens':22066,'prior_output_tokens':0})
    assert result['status']=='partial'
    assert result['reported_completed_request_output_tokens']==22066
    assert result['output_tokens'] is None and result['inflight_usage_unknown']

def test_shared_recovery_budget_does_not_include_prior_attempt_twice():
    result=preserve_completed_request_bound({'status':'missing','output_tokens':None},
                      {'reported_output_tokens':31000,'prior_output_tokens':10000})
    assert result['reported_completed_request_output_tokens']==21000

def test_recorded_terminal_usage_is_authoritative():
    result=preserve_completed_request_bound({'status':'recorded','output_tokens':123},
                      {'reported_output_tokens':120,'prior_output_tokens':0})
    assert result['output_tokens']==123 and 'inflight_usage_unknown' not in result
