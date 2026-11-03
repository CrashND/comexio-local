import asyncio
import json
import pytest
from comexio_local.discovery import discover
from comexio_local.tcp_client import ComexioTCPClient
from test_discovery import _config

@pytest.mark.asyncio
async def test_tcp_read_group_and_writes_are_one_shot():
    requests=[]
    current={'io:IO-Ext-2/Q1':0,'cover:M79':42}

    async def serve(reader,writer):
        data=await reader.readline()
        commands=json.loads(data)
        requests.append(commands)
        response={}
        for key,command in commands.items():
            if command['action']=='get':
                value=(current['cover:M79'] if command.get('marker')=='M79' else current['io:IO-Ext-2/Q1'])
                response[key]=value
            elif command['action']=='set':
                response[key]=command['value']
                if command.get('io')=='Q1':current['io:IO-Ext-2/Q1']=command['value']
        writer.write((json.dumps(response)+'\n').encode())
        await writer.drain()
        writer.close()

    server=await asyncio.start_server(serve,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    client=ComexioTCPClient('127.0.0.1',port)
    found=discover(_config())
    light=found['io:IO-Ext-2/Q1']; cover=found['cover:M79']
    state=await client.read_sources([light,cover])
    assert state=={'io:IO-Ext-2/Q1':False,'cover:M79':42}
    assert len(requests)==1 and len(requests[0])==2
    await client.set_channel(light,True)
    assert (await client.read_sources([light]))[light.key] is True
    await client.write_marker(78,100)
    assert requests[-1]['set']['marker']=='M78'
    assert len(requests)==4
    server.close()
    await server.wait_closed()
