"""Readable Web-IO class names and backward compatibility tests."""

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import discover
from comexio_local.name_migration import inspect_names
from comexio_local.push_audit import audit_config
from comexio_local.push_labels import PREFERRED_PUSH_CLASS, push_class_candidates
from comexio_local.push_setup import _find_push_device, push_sources
from test_discovery import _config
from test_push_audit import ENTRY, PATH, BASE, _installed


def test_class_name_is_clear_and_old_name_is_still_recognized():
    prefix = 'CL' + ENTRY[:8].upper()
    assert push_class_candidates(prefix) == (f'{prefix} Push', 'CL Push Home Assistant')
    assert PREFERRED_PUSH_CLASS == 'CL Push Home Assistant'
    config, plans, channels = _installed()
    assert _find_push_device(config, prefix) == ('19', f'{prefix} Push')
    config['WebDevices']['19']['Name'] = PREFERRED_PUSH_CLASS
    assert _find_push_device(config, prefix) == ('19', PREFERRED_PUSH_CLASS)
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.linked == report.sources == len(push_sources(channels))
    assert not report.errors
    assert not inspect_names(config, channels, ENTRY)['blockers']


def test_new_class_is_preferred_on_empty_comexio_setup():
    prefix = 'CL' + ENTRY[:8].upper()
    device_id, name = _find_push_device(_config(), prefix)
    assert device_id is None
    assert name == PREFERRED_PUSH_CLASS


def test_duplicate_legacy_and_new_class_blocks_writes():
    prefix = 'CL' + ENTRY[:8].upper()
    config, _, _ = _installed()
    config['WebDevices']['20'] = {'Name': PREFERRED_PUSH_CLASS}
    with pytest.raises(AdminError, match='Mehrere'):
        _find_push_device(config, prefix)


def test_duplicate_readable_class_also_blocks_writes():
    prefix = 'CL' + ENTRY[:8].upper()
    config, _, _ = _installed()
    config['WebDevices']['19']['Name'] = PREFERRED_PUSH_CLASS
    config['WebDevices']['20'] = {'Name': PREFERRED_PUSH_CLASS}
    with pytest.raises(AdminError, match='Mehrere'):
        _find_push_device(config, prefix)
