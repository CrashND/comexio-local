"""Persistent cover polarity and manual IO classification regression checks."""
from dataclasses import replace
import pytest

from comexio_local.discovery import Channel
from comexio_local.preferences import (
    apply_classifications, cover_is_inverted, ha_cover_position,
    comexio_cover_target, is_classifiable, pin_existing_kinds,
)


@pytest.fixture
def signals():
    light = Channel(kind='light', name='Buero Licht', key='io:IO-Ext-2/Q2',
                    extension='IO-Ext-2', identifier='Q2', io_id=21)
    unknown = Channel(kind='relay', name='Kueche WZ INDEREKT', key='io:IO-Ext-3/Q1',
                      extension='IO-Ext-3', identifier='Q1', io_id=1)
    motor = Channel(kind='motor', name='Roll Motorausgang', key='io:IO-Ext-3/Q3',
                    extension='IO-Ext-3', identifier='Q3', io_id=3)
    cover = Channel(kind='cover', name='Rollladen Buero', key='cover:M85',
                    marker_id=85, target_marker_id=84, analog=True)
    return {c.key: c for c in (light, unknown, motor, cover)}


def test_cover_default_backward_compatible_and_exception():
    key = 'cover:M85'
    assert cover_is_inverted({}, key) is False
    assert cover_is_inverted({'cover_invert_default':True}, key) is True
    assert cover_is_inverted({'cover_invert_default':True, 'cover_invert_overrides':{key:False}}, key) is False
    assert cover_is_inverted({'cover_invert_default':False, 'cover_invert_overrides':{key:True}}, key) is True
    assert cover_is_inverted({'cover_invert_default':True, 'cover_invert_overrides':{key:'yes'}}, key) is True


def test_cover_positions_are_bidirectional_and_bounded():
    assert ha_cover_position(0, True) == 100
    assert ha_cover_position(100, True) == 0
    assert ha_cover_position(25, True) == 75
    assert ha_cover_position(25, False) == 25
    assert ha_cover_position(-20, True) == 100
    assert ha_cover_position(120, False) == 100
    assert ha_cover_position(None, True) is None
    assert comexio_cover_target(100, True) == 0
    assert comexio_cover_target(0, True) == 100
    assert comexio_cover_target(0, False) == 0
    with pytest.raises(ValueError):
        comexio_cover_target(101, True)


def test_user_can_classify_unknown_output_but_not_motor(signals):
    unknown = signals['io:IO-Ext-3/Q1']
    motor = signals['io:IO-Ext-3/Q3']
    assert is_classifiable(unknown)
    assert not is_classifiable(motor)
    options = {'channel_kind_overrides':{unknown.key:'light', motor.key:'light'}}
    applied = apply_classifications(signals, options)
    assert applied[unknown.key].kind == 'light'
    assert applied[unknown.key].manually_classified
    assert applied[motor.key].kind == 'motor'
    assert not applied[motor.key].is_push_source
    assert applied[unknown.key].is_push_source


def test_status_is_read_only_but_can_receive_push(signals):
    light = signals['io:IO-Ext-2/Q2']
    applied = apply_classifications(signals, {'channel_kind_overrides':{light.key:'relay'}})
    assert applied[light.key].kind == 'relay'
    assert applied[light.key].is_push_source
    assert not light.manually_classified
    assert light.is_push_source


def test_stable_inferred_type_survives_label_changes(signals):
    unknown = signals['io:IO-Ext-3/Q1']
    pinned = pin_existing_kinds(signals, {})
    assert pinned[unknown.key] == 'relay'
    corrected = replace(unknown, kind='light', name='Kueche WZ INDIREKT')
    result = apply_classifications({unknown.key:corrected}, {'known_channel_kinds':pinned})
    assert result[unknown.key].kind == 'relay'
    result = apply_classifications({unknown.key:corrected}, {})
    assert result[unknown.key].kind == 'light'


def test_addresses_unchanged_after_classification(signals):
    raw = signals['io:IO-Ext-3/Q1']
    edited = apply_classifications({raw.key:raw}, {'channel_kind_overrides':{raw.key:'switch'}})[raw.key]
    assert edited.key == raw.key
    assert edited.source == raw.source
    assert edited.io_id == raw.io_id
    assert edited.kind == 'switch'


def test_motor_pin_cannot_be_reclassified_after_description_rename(signals):
    from dataclasses import replace
    motor = signals['io:IO-Ext-3/Q3']
    renamed = replace(motor, kind='relay', name='Unbenannter Ausgang')
    options = {'known_channel_kinds':{motor.key:'motor'},
               'channel_kind_overrides':{motor.key:'light'}}
    assert apply_classifications({motor.key:renamed}, options)[motor.key].kind == 'motor'
