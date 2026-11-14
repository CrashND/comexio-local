"""Fail if a maintenance menu is missing labels or private docs enter source."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / 'custom_components' / 'comexio_local'


def test_all_options_menu_entries_have_german_and_english_labels():
    source = json.loads((DOMAIN / 'strings.json').read_text())
    german = json.loads((DOMAIN / 'translations/de.json').read_text())
    english = json.loads((DOMAIN / 'translations/en.json').read_text())
    menus = {
        'init': {'push_management', 'devices_menu', 'covers_menu', 'maintenance_menu'},
        'push_management': {'inputs_menu', 'outputs_push_menu'},
        'inputs_menu': {'input_select', 'input_enocean_select', 'input_status'},
        'outputs_push_menu': {'repair_select', 'rebuild_preview', 'rebuild_status'},
        'devices_menu': {'area_auto','area_manual','classify_select'},
        'covers_menu': {'cover_global','cover_single'},
        'maintenance_menu': {'sync_preview','names_preview'},
    }
    expected_actions = set().union(*(v for k,v in menus.items() if k!='init'))
    assert len(expected_actions) == sum(len(v) for k,v in menus.items() if k!='init')
    for item in (source,german,english):
        options = item['options']['step']
        for name, children in menus.items():
            assert set(options[name]['menu_options']) == children
            assert all(options[name]['menu_options'].values())
            assert options[name]['title']
            assert options[name]['description']
            assert all(child in options for child in children)
    assert not (set(menus['init']) & expected_actions)


def test_config_flow_exposes_exact_menu_groups_and_actions():
    import ast
    root = ast.parse((DOMAIN / 'config_flow.py').read_text())
    cls = next(node for node in root.body if isinstance(node, ast.ClassDef)
               and node.name == 'ComexioLocalOptionsFlow')
    funcs = {node.name:node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)}
    groups = {
        'async_step_init':['push_management','devices_menu','covers_menu','maintenance_menu'],
        'async_step_inputs_menu':['input_select','input_enocean_select','input_status'],
        'async_step_outputs_push_menu':['repair_select','rebuild_preview','rebuild_status'],
        'async_step_devices_menu':['area_auto','area_manual','classify_select'],
        'async_step_covers_menu':['cover_global','cover_single'],
        'async_step_maintenance_menu':['sync_preview','names_preview'],
        'async_step_push_management':['inputs_menu','outputs_push_menu'],
    }
    for fname,expected in groups.items():
        assert fname in funcs
        calls = [n for n in ast.walk(funcs[fname]) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr=='async_show_menu']
        assert len(calls)==1
        arg = next(kw.value for kw in calls[0].keywords if kw.arg=='menu_options')
        if fname in ('async_step_inputs_menu', 'async_step_outputs_push_menu'):
            # Dynamic prioritization moves a running status job to the top.
            assert all(action in ast.unparse(funcs[fname]) for action in expected)
        else:
            assert ast.literal_eval(arg)==expected



def test_version_parity_and_public_file_policy():
    manifest = json.loads((DOMAIN / 'manifest.json').read_text())
    assert manifest["version"] == "0.4.5"
    assert 'INTEGRATION_VERSION = "0.4.5"' in (DOMAIN / 'constants.py').read_text()
    assert ('**Aktuelle Version:** ' + manifest['version']) in (ROOT / 'README.md').read_text()
    assert not list(ROOT.glob('RELEASE_*.md'))
    assert not list(ROOT.glob('*PROJEKTSTAND*.md'))
    gitignore=(ROOT/'.gitignore').read_text()
    assert 'RELEASE_*.md' in gitignore and 'PROJEKTSTAND*.md' in gitignore


def test_new_status_actions_and_enocean_forms_are_translated():
    for path in (DOMAIN / 'strings.json', DOMAIN / 'translations/de.json',
                 DOMAIN / 'translations/en.json'):
        entries = json.loads(path.read_text())['options']['step']
        assert entries['input_status']['submit']
        assert entries['input_status_finished']['submit']
        assert entries['input_status']['submit'] != entries['input_status_finished']['submit']
        assert 'input_mode' not in entries['input_enocean_select']['data']
        assert entries['input_select']['data']['input_mode']
        for key in ('push_management','inputs_menu','outputs_push_menu','init'):
            assert set(entries[key]['menu_option_descriptions']) == set(entries[key]['menu_options'])
