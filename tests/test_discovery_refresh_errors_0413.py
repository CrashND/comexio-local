"""v0.4.13: the options-flow refresh keeps the original safe HTTP/timeout detail.

Offline regression. COMEXIO is not contacted by these tests.
"""
from __future__ import annotations

import asyncio

import pytest

from comexio_local.admin_api import AdminError
from test_input_flow_03633 import _load_options_flow


class FakeHttpFailure(Exception):
    def __init__(self, status: int, url: str) -> None:
        self.status = status
        super().__init__(url)


@pytest.mark.parametrize('underlying,detail', [
    (FakeHttpFailure(503, 'http://192.168.1.99/api/webhook/secret-123?token=private'), 'HTTP 503'),
    (TimeoutError('http://192.168.1.99/private?password=private'), 'Zeitlimit bei COMEXIO-Anfrage'),
])
def test_menu_keeps_root_cause_and_hides_private_data(monkeypatch, caplog, underlying, detail):
    module = _load_options_flow(monkeypatch)

    class FailingRuntime:
        def __init__(self):
            self.calls = 0
            self.channels = {'io:EnOcean/EI5_CO': object()}
        async def refresh_discovery(self):
            self.calls += 1
            try:
                raise underlying
            except Exception as exc:
                raise AdminError('COMEXIO configuration discovery failed') from exc

    runtime = FailingRuntime()
    flow = module.ComexioLocalOptionsFlow()
    flow._runtime = lambda: runtime
    form = asyncio.run(flow.async_step_discovery_refresh())
    assert form['type'] == 'form'
    assert form['errors']['base'] == 'cannot_connect'
    reason = form['description_placeholders']['summary']
    assert detail in reason
    assert 'COMEXIO configuration discovery failed' in reason
    assert '192.168.1.99' not in reason
    assert 'secret-123' not in reason
    assert 'token=private' not in reason
    assert 'password=private' not in reason
    assert runtime.calls == 1
    assert set(runtime.channels) == {'io:EnOcean/EI5_CO'}
    assert detail in caplog.text
    assert '192.168.1.99' not in caplog.text
