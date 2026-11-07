"""Canonical COMEXIO Local Web-IO class names and collision guards."""
import pytest

from comexio_local.admin_api import AdminError
from comexio_local.name_inspection import inspect_names
from comexio_local.push_audit import audit_config
from comexio_local.push_labels import PREFERRED_PUSH_CLASS
from comexio_local.push_setup import _find_push_device, push_sources
from test_discovery import _config
from test_push_audit import ENTRY, PATH, BASE, _installed


def test_single_canonical_class_is_found_and_audited():
    assert PREFERRED_PUSH_CLASS == 'CL Push Home Assistant'
    config, plans, channels = _installed()
    assert _find_push_device(config) == ('19', PREFERRED_PUSH_CLASS)
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.linked == report.sources == len(push_sources(channels))
    assert not report.errors
    assert not inspect_names(config, channels, ENTRY)['blockers']


def test_new_class_name_is_used_on_clean_setup():
    assert _find_push_device(_config()) == (None, PREFERRED_PUSH_CLASS)


def test_noncanonical_class_does_not_match():
    config, _, _ = _installed()
    config['WebDevices']['19']['Name'] = 'Manuelle Testklasse'
    assert _find_push_device(config) == (None, PREFERRED_PUSH_CLASS)


def test_duplicate_canonical_class_blocks_writes():
    config, _, _ = _installed()
    config['WebDevices']['20'] = {'Name': PREFERRED_PUSH_CLASS}
    with pytest.raises(AdminError, match='Mehrere'):
        _find_push_device(config)
