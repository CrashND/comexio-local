"""One-shot discovery synchronization preview never mutates source channels."""
from dataclasses import replace
from comexio_local.discovery import Channel
from comexio_local.discovery_sync import compare_catalog


def _channel(key, kind='light', name='SZ Licht'):
    return Channel(kind=kind, name=name, key=key, extension='IO-Ext-1',
                   identifier='Q1', io_id=10)


def test_rename_preserves_address_and_domain():
    key='io:IO-Ext-1/Q1'
    old={key: _channel(key)}
    current={key: replace(old[key], name='Schlafzimmer Licht')}
    result=compare_catalog(old, current, {})
    assert result['counts']['renamed']==1
    assert result['rows'][0]['key']==key
    assert not result['requires_manual_classification']
    assert old[key].name=='SZ Licht'


def test_types_are_never_silently_migrated():
    old={'x':_channel('x','relay')}
    new={'x':_channel('x','light')}
    result=compare_catalog(old,new,{})
    assert result['requires_manual_classification']
    assert result['counts']['type_changed']==1


def test_add_remove_and_stale_fingerprint():
    before={'a':_channel('a'),'b':_channel('b')}
    after={'a':_channel('a'),'c':_channel('c')}
    snapshot=compare_catalog(before,after,{})
    assert snapshot['counts']['added']==1
    assert snapshot['counts']['removed']==1
    assert compare_catalog(before,after,{})['fingerprint']==snapshot['fingerprint']
    assert compare_catalog(before,after,{'cover_invert_default':True})['fingerprint'] != snapshot['fingerprint']
    assert compare_catalog(before,{'a':_channel('a')}, {})['fingerprint'] != snapshot['fingerprint']
