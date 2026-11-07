"""Reusable COMEXIO Local-owned plan graph utilities.

Never infer ownership from the graph.  Callers must first establish a valid
plan-owner tag and a trusted target command.  Writes are never retried here.
"""
from __future__ import annotations

from .admin_api import AdminError, ComexioAdmin
from .discovery import Channel

PLAN_ROWS = 18


def plan_elements(plan: dict) -> tuple[dict[tuple[int,int],int], list[set[int]]]:
    refs={}
    connections=[]
    for eid,elem in (plan.get("elements") or {}).items():
        try:
            ref=elem["reference"]
            refs[int(ref["type"]),int(ref["ref_id"])]=int(eid)
        except (KeyError,ValueError,TypeError):
            continue
    for conn in (plan.get("connections") or {}).values():
        endpoints=set()
        output=conn.get("output") or []
        if isinstance(output,dict): output=output.values()
        for o in [conn.get("input") or {},*output]:
            try:
                endpoints.add(int(o.get("FubElementId", o.get("element"))))
            except (AttributeError,TypeError,ValueError):
                pass
        connections.append(endpoints)
    return refs,connections


async def ensure_webio_link(admin: ComexioAdmin, plan_id: int, signal: Channel,
                            command_id: int, index: int, plan: dict, *,
                            update_cache: bool) -> bool:
    """Idempotently add a physical/marker source and one Web-IO output link.

    `update_cache=True` is used by the resumable and input worksets. The old
    one-shot setup reads the real graph between operations, so it does not need
    the in-memory cache (update_cache=False). No COMEXIO writes are repeated.
    """
    source_type = 2 if signal.kind == 'cover' else 1
    source_ref = signal.marker_id if signal.kind == 'cover' else signal.io_id
    if source_ref is None:
        raise AdminError('COMEXIO-Quellenreferenz fehlt: ' + signal.key)
    if not isinstance(plan.get('elements'), dict) or not isinstance(plan.get('connections'), dict):
        raise AdminError('COMEXIO-Logikplan hat ein unbekanntes Graphformat; keine Änderung')
    refs, edges = plan_elements(plan)
    element_ids = {int(eid) for eid in plan['elements'] if str(eid).isdigit()}
    if len(refs) != len(plan['elements']) or len(element_ids) != len(plan['elements']):
        raise AdminError('COMEXIO-Logikplan enthält nicht eindeutig lesbare Bausteine; keine Änderung')
    if any(not endpoints or not endpoints <= element_ids for endpoints in edges):
        raise AdminError('COMEXIO-Logikplan enthält nicht eindeutig lesbare Verbindungen; keine Änderung')
    src = refs.get((source_type, int(source_ref)))
    dst = refs.get((10, int(command_id)))
    if src is not None and dst is not None and any(src in e and dst in e for e in edges):
        return False

    x0, x1, y = 40, 400, 25 + (index % PLAN_ROWS) * 35
    if src is None:
        src = await admin.add_element(plan_id, int(source_ref), source_type, x0, y)
        if update_cache:
            plan.setdefault('elements', {})[str(src)] = {
                'reference': {'type': source_type, 'ref_id': int(source_ref)}}

    if dst is None:
        connection = {'0': {'id': 'new', 'fub_id': plan_id,
                      'type': 'analog' if signal.analog else 'binary',
                      'input': {'element': str(src), 'pos': '0', 'inverted': False},
                      'output': {'0': {'element': 'new', 'pos': '0', 'inverted': False}}}}
        dst = await admin.add_element(plan_id, int(command_id), 10, x1, y,
                                      connection=connection)
        if update_cache:
            plan.setdefault('elements', {})[str(dst)] = {
                'reference': {'type': 10, 'ref_id': int(command_id)}}
    else:
        await admin.wire(plan_id, src, dst, signal.analog)

    if update_cache:
        plan.setdefault('connections', {})[f'new-{src}-{dst}'] = {
            'input': {'element': str(src)},
            'output': {'0': {'element': str(dst)}}}
    return True
