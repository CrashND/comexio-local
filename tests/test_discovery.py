from comexio_local.discovery import discover,event_address
from comexio_local.admin_api import extract_config, make_push_command


def _config(relay_name='GZ Licht', io_address='Q1', marker_num=79):
    return {'FubModules': {'1': {'5': {'extension': {'Name':'IO-Ext-2'},
        'inoutput': {'4': {'Id': 4,'Identifier':io_address,'Active':1,'Description':relay_name},
                     '7': {'Id':7,'Identifier':'Q2','Active':1,'Description':'Roll GZ H'},
                     '8': {'Id':8,'Identifier':'Q3','Active':1,'Description':'Roll GZ AB'},
                     '9': {'Id':9,'Identifier':'Q4','Active':1,'Description':'Hilfsrelais'}}}},
        '2': {'78': {'Id':78,'Name':'R_Gast_soll','Type':2},
              str(marker_num): {'Id':marker_num,'Name':'R_Gast_ist','Type':2}}},
        'Fubs': {'13': {'Name':'Gaestezimmer','Comment':'Eigenlogik'}}}


def test_discovery_classifies_all_sources_without_fixed_map():
    config=_config()
    plan={'13': {'elements': {'1': {'reference': {'type':1,'ref_id':4}},
                              '2': {'reference': {'type':1,'ref_id':7}}}}}
    found=discover(config,plan)
    assert found['io:IO-Ext-2/Q1'].kind=='light'
    assert 'Gaestezimmer' in found['io:IO-Ext-2/Q1'].name
    assert found['io:IO-Ext-2/Q2'].kind=='motor'
    assert found['io:IO-Ext-2/Q3'].kind=='motor'
    assert found['io:IO-Ext-2/Q4'].kind=='relay'
    assert found['cover:M79'].kind=='cover'
    assert found['cover:M79'].target_marker_id==78
    assert 'io:IO-Ext-2/Q2' not in [c.key for c in found.values() if c.is_push_source]


def test_discovery_dynamic_rename_new_io_and_changed_marker_id():
    changed=_config(relay_name='Kueche LED', io_address='Q10',marker_num=185)
    result=discover(changed)
    assert 'io:IO-Ext-2/Q1' not in result
    assert result['io:IO-Ext-2/Q10'].kind=='light'
    assert 'cover:M185' in result
    assert event_address({'type':'io','ext':'IO-Ext-2','io':'Q10','value':1})=='io:IO-Ext-2/Q10'
    assert event_address({'type':'marker','id':'185','value':50})=='cover:M185'


def test_admin_html_parser_extracts_multiple_script_objects():
    html='<script>var $FubModules = {"1": {"x": {"Name": "Hallo"}}}; var $Fubs={"1":{"Name":"Raum"}};</script>'
    data=extract_config(html)
    assert data['FubModules']['1']['x']['Name']=='Hallo'
    assert data['Fubs']['1']['Name']=='Raum'


def test_webio_lua_uses_actual_source():
    found=discover(_config())
    cmd=make_push_command('TEST',found['io:IO-Ext-2/Q1'],'/api/webhook/abcdef')
    assert '"IO-Ext-2"' in cmd['Data']
    assert '"Q1"' in cmd['Data']
    assert cmd['Parameter']=='/api/webhook/abcdef'
    cover=make_push_command('TEST',found['cover:M79'],'/api/webhook/abcdef')
    assert '"79"' in cover['Data']
