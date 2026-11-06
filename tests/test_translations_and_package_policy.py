"""Fail if a maintenance menu is missing labels or private docs enter source."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / 'custom_components' / 'comexio_local'


def test_all_options_menu_entries_have_german_and_english_labels():
    source = json.loads((DOMAIN / 'strings.json').read_text())
    german = json.loads((DOMAIN / 'translations/de.json').read_text())
    english = json.loads((DOMAIN / 'translations/en.json').read_text())
    keys = set(source['options']['step']['init']['menu_options'])
    assert keys == {'area_auto','area_manual','names_preview',
                    'cover_global','cover_single','classify_select','sync_preview',
                    'push_management'}
    for item in (source,german,english):
        options = item['options']['step']
        assert set(options['init']['menu_options']) == keys
        assert all(options['init']['menu_options'].values())
        assert all(key in options for key in keys)
        nested = {'repair_select', 'input_select', 'rebuild_preview', 'rebuild_status'}
        assert set(options['push_management']['menu_options']) == nested
        assert all(options['push_management']['menu_options'].values())
        assert all(key in options for key in nested)


def test_version_parity_and_public_file_policy():
    manifest = json.loads((DOMAIN / 'manifest.json').read_text())
    assert manifest['version'] == '0.3.6.3.1'
    assert 'INTEGRATION_VERSION = "0.3.6.3.1"' in (DOMAIN / 'constants.py').read_text()
    assert ('**Aktuelle Version:** ' + manifest['version']) in (ROOT / 'README.md').read_text()
    assert not list(ROOT.glob('RELEASE_*.md'))
    assert not list(ROOT.glob('*PROJEKTSTAND*.md'))
    gitignore=(ROOT/'.gitignore').read_text()
    assert 'RELEASE_*.md' in gitignore and 'PROJEKTSTAND*.md' in gitignore
