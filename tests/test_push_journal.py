"""v0.3.2 diagnostics only: no HA instance or COMEXIO hardware needed."""
from datetime import datetime, timezone
from comexio_local.push_journal import PushJournal


def test_events_keep_source_value_time_and_boolean_conversion():
    journal = PushJournal(capacity=4)
    at = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
    event = journal.record(
        source='io:IO-Ext-2/Q2', name='Buero Licht', kind='light',
        value=True, previous=False, entity_id='light.buero', received_at=at,
    )
    assert event == {
        'seq': 1,
        'received_at_utc': '2026-11-03T10:00:00.000+00:00',
        'source': 'io:IO-Ext-2/Q2',
        'name': 'Buero Licht',
        'kind': 'light',
        'value': 1,
        'previous_cached_value': 0,
        'changed_since_cached': True,
        'entity_id': 'light.buero',
    }
    assert journal.total == 1
    assert journal.sources()['io:IO-Ext-2/Q2']['count'] == 1


def test_duplicate_values_and_unknown_previous_are_distinguished():
    journal = PushJournal()
    first = journal.record(source='io:IO-Ext-1/Q4', name='Duschbad', kind='light', value=1, previous=None)
    second = journal.record(source='io:IO-Ext-1/Q4', name='Duschbad', kind='light', value=1, previous=True)
    assert first['changed_since_cached'] is None
    assert second['changed_since_cached'] is False
    assert journal.same_as_cached == 1
    assert journal.sources()['io:IO-Ext-1/Q4']['same_as_cached'] == 1
    assert journal.total == 2


def test_bounded_tail_and_source_counts_track_all_events():
    journal = PushJournal(capacity=3)
    for n in range(7):
        journal.record(source='io:IO-Ext-1/Q4' if n % 2 == 0 else 'io:IO-Ext-2/Q2',
                       name='Test', kind='light', value=n % 2, previous=None)
    result = journal.report(limit=10)
    assert result['total_since_start'] == 7
    assert result['retained_events'] == 3
    assert [ev['seq'] for ev in result['last_events']] == [7, 6, 5]
    assert result['unique_sources'] == 2
    assert result['sources']['io:IO-Ext-1/Q4']['count'] == 4
    assert result['sources']['io:IO-Ext-2/Q2']['count'] == 3


def test_cover_position_keeps_decimal_value():
    journal = PushJournal()
    event = journal.record(source='cover:M75', name='Rollladen Duschbad', kind='cover',
                           value=27.5, previous=0)
    assert event['value'] == 27.5
    assert event['previous_cached_value'] == 0
    assert event['changed_since_cached'] is True


def test_immutable_report_copies_do_not_modify_internal_records():
    journal = PushJournal()
    journal.record(source='io:IO-Ext-2/Q2', name='B', kind='light', value=1, previous=0)
    report = journal.report()
    report['last_events'][0]['value'] = 99
    report['sources']['io:IO-Ext-2/Q2']['count'] = 200
    assert journal.report()['last_events'][0]['value'] == 1
    assert journal.report()['sources']['io:IO-Ext-2/Q2']['count'] == 1
