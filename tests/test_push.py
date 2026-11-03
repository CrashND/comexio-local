from comexio_local.discovery import discover
from comexio_local.push_setup import push_sources, _stable_groups, _plan_elements
from test_discovery import _config


def test_push_targets_only_relevant_and_stable():
    a=discover(_config())
    signals=push_sources(a)
    assert {c.key for c in signals}=={'io:IO-Ext-2/Q1','cover:M79'}
    groups=_stable_groups(signals)
    assert len(groups)==2
    # Another output in a different extension cannot move the original group.
    next_group=_stable_groups(signals)
    assert [x[0] for x in groups]==[x[0] for x in next_group]


def test_existing_connection_recognition_two_endpoint_formats():
    payload={'elements':{'101':{'reference':{'type':1,'ref_id':4}},
                         '102':{'reference':{'type':10,'ref_id':12}}},
             'connections':{'9':{'input':{'element':'101'},'output':{'0':{'FubElementId':'102'}}}}}
    refs,edges=_plan_elements(payload)
    assert refs[(1,4)]==101
    assert {101,102} in edges
