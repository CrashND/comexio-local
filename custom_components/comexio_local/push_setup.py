"""Explicit, incremental Web-IO push installation.

Unlike an unrestricted full sync, only confirmed light outputs and actual cover
position markers are linked. Never touches the original user room plans.
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit
from .admin_api import AdminError, ComexioAdmin, command_name, make_push_command
from .discovery import Channel

_LOGGER=logging.getLogger(__name__)
MAX_SIGNALS_PER_PLAN=18


def push_sources(channels: dict[str, Channel]) -> list[Channel]:
    return sorted((c for c in channels.values() if c.kind in ("light", "cover")),key=lambda c:c.key)


def _stable_groups(signals: list[Channel]) -> list[tuple[str, list[Channel]]]:
    """Keep device-to-plan association stable as new IOs are added in other modules."""
    groups: dict[str, list[Channel]] = {}
    for signal in signals:
        bucket = signal.extension if signal.kind == "light" else "POSITIONEN"
        groups.setdefault(bucket, []).append(signal)
    grouped = []
    for bucket in sorted(groups):
        signals_in_module = sorted(groups[bucket], key=lambda s: s.key)
        # Short deterministic name avoids COMEXIO plan-name length/character limitations.
        import zlib
        label = f"G{zlib.crc32(bucket.encode()):08X}"
        for start in range(0,len(signals_in_module),MAX_SIGNALS_PER_PLAN):
            suffix = start // MAX_SIGNALS_PER_PLAN
            grouped.append((f"{label}-{suffix}", signals_in_module[start:start+MAX_SIGNALS_PER_PLAN]))
    return grouped


def _existing_commands(config: dict, device_id: str) -> dict[str,int]:
    in_dev=(config.get("FubModules") or {}).get("10",{}).get(str(device_id),{})
    return {str(c.get("Name")):int(cid) for cid,c in in_dev.items() if isinstance(c,dict) and c.get("Name")}


def _find_device(config: dict, name: str) -> str | None:
    return next((str(did) for did,dev in (config.get("WebDevices") or {}).items()
                 if isinstance(dev,dict) and dev.get("Name")==name),None)


def _find_plan(config: dict, name: str) -> tuple[int,dict] | None:
    return next(((int(fid),val) for fid,val in (config.get("Fubs") or {}).items()
                 if isinstance(val,dict) and val.get("Name")==name),None)


def _plan_elements(plan: dict) -> tuple[dict[tuple[int,int],int], list[set[int]]]:
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


async def _get_base_id(admin: ComexioAdmin, name: str) -> str:
    page=await admin._get_html("/admin/web_io/add")
    pattern=r'<option\s+value="(\d+)"[^>]*>\s*'+re.escape(name)+r'\s*</option>'
    match=re.search(pattern,page,re.I)
    if match is None:
        raise AdminError("Could not resolve existing Web-IO base ID; not overwriting it")
    return match.group(1)


async def _append_command(admin: ComexioAdmin, device_id: str, base_id: str, cmd: dict) -> None:
    """Append one command without modifying any existing Web-IO command."""
    empty_ref=base64.b64encode(b'{"src":"command","id":null}').decode("ascii")
    data={
      "dlg_web_device_id":str(device_id),"protocol":0,"parameter":cmd["Parameter"],
      "header_modifier":cmd["HeaderModifier"],"data":cmd["Data"],"port":"",
      "post_get":1,"authentication":0,"req_freq":"","reply_interpreter":"",
      "id_cmd_io_0":empty_ref,"name_cmd_io_0":cmd["Name"],
      "function_cmd_io_0":"1_1_0","input_cmd_io_0":1,
      "type_cmd_io_0":cmd["TypeId"],"send_on_one_cmd_io_0":0,
      "min_cmd_io_0":0,"max_cmd_io_0":cmd["Max"],"default_value_cmd_io_0":"",
      "id_cmd_io_sample":"","name_cmd_io_sample":"","function_cmd_io_sample":"0_1_0",
      "input_cmd_io_sample":1,"type_cmd_io_sample":2,"send_on_one_cmd_io_sample":0,
      "min_cmd_io_sample":0,"max_cmd_io_sample":1,"default_value_cmd_io_sample":"",
      "DefaultActive":1,"deviceBaseId":str(base_id),
    }
    # COMEXIO save_command returns 200 on success; inspect later via raw discovery.
    async with admin._lock:
        await asyncio.sleep(0.35)
        admin._last_write=asyncio.get_running_loop().time()
        async with admin.session.post(admin.base+"/admin/web_io/save_command",data=data,headers=admin._headers) as response:
            if response.status != 200:
                raise AdminError(f"Web-IO command '{cmd['Name']}' failed: HTTP {response.status}")


async def _wire_pair(admin: ComexioAdmin, plan_id: int, signal: Channel, command_id: int,
                     index: int, plan: dict) -> bool:
    source_type=2 if signal.kind=="cover" else 1
    source_ref=signal.marker_id if signal.kind=="cover" else signal.io_id
    if source_ref is None:
        raise AdminError("Missing COMEXIO source reference for " + signal.name)
    refs,connections=_plan_elements(plan)
    src=refs.get((source_type,int(source_ref)))
    dest=refs.get((10,int(command_id)))
    if src is not None and dest is not None and any(src in c and dest in c for c in connections):
        return False
    x0,x1,y=40,400,25+(index % MAX_SIGNALS_PER_PLAN)*35
    if src is None:
        src=await admin.add_element(plan_id,int(source_ref),source_type,x0,y)
    if dest is not None:
        await admin.wire(plan_id,src,dest,signal.analog)
    else:
        conn={"0":{"id":"new","fub_id":plan_id,
                 "type":"analog" if signal.analog else "binary",
                 "input":{"element":str(src),"pos":"0","inverted":False},
                 "output":{"0":{"element":"new","pos":"0","inverted":False}}}}
        await admin.add_element(plan_id,int(command_id),10,x1,y,connection=conn)
    # Preserve in-memory topology to avoid adding another source element on next pair.
    return True


async def configure_push(admin:ComexioAdmin, channels:dict[str,Channel],entry_id:str,
                         webhook_path:str,push_base:str) -> dict[str,int]:
    """Apply after explicit user consent and existing full COMEXIO backup."""
    signals=push_sources(channels)
    if not signals:
        raise AdminError("No lights or actual cover position markers discovered")
    if len(signals)>90:
        raise AdminError("Too many push sources; select a smaller installation before setup")
    parsed=urlsplit(push_base)
    if parsed.scheme!="http" or not parsed.hostname or not parsed.port:
        raise AdminError("Push target must be a LAN http://HOST:PORT address")
    host_port=f"{parsed.hostname}:{parsed.port}"
    short=entry_id[:8].upper()
    prefix=f"CL{short}"
    class_name=f"{prefix} Push"
    marker_comment=f"Managed exclusively by COMEXIO Local ({entry_id}), do not rename"
    status={"created_commands":0,"added_pairs":0,"activated_plans":0}
    config=await admin.read_config()
    device_id=_find_device(config,class_name)
    if device_id is None:
        # New class only. This name must be unique; never reuse another integration's class.
        commands=[make_push_command(prefix,c,webhook_path) for c in signals]
        await admin.create_push_class(class_name,commands,host_port)
        config=await admin.read_config()
        device_id=_find_device(config,class_name)
        if device_id is None:
            raise AdminError("Web-IO device not visible after creation. No further changes made")
        status["created_commands"]=len(commands)
    existing=_existing_commands(config,device_id)
    missing=[c for c in signals if command_name(prefix,c) not in existing]
    if missing:
        base_id=await _get_base_id(admin,class_name)
        for c in missing:
            await _append_command(admin,device_id,base_id,make_push_command(prefix,c,webhook_path))
            status["created_commands"]+=1
        config=await admin.read_config()
        existing=_existing_commands(config,device_id)
    for group_name,group in _stable_groups(signals):
        name=f"{prefix} {group_name}"
        info=_find_plan(config,name)
        if info:
            plan_id,meta=info
            if entry_id not in str(meta.get("Comment", "")):
                raise AdminError(f"Refusing to modify unowned plan {name}")
        else:
            plan_id=await admin.create_plan(name,marker_comment)
            config=await admin.read_config()
        plan=await admin.read_plan(plan_id)
        changed=False
        for k,signal in enumerate(group):
            command_id=existing.get(command_name(prefix,signal))
            if command_id is None:
                raise AdminError("Web-IO command ID not visible: " + signal.name)
            if await _wire_pair(admin,plan_id,signal,command_id,k,plan):
                status["added_pairs"]+=1
                changed=True
                plan=await admin.read_plan(plan_id)
        plan_active = (config.get("Fubs") or {}).get(str(plan_id),{}).get("Active")
        if changed or str(plan_active).lower() not in ("1", "true"):
            await admin.run_plan(plan_id)
            status["activated_plans"]+=1
    _LOGGER.info("COMEXIO Local push installed: %s",status)
    return status
