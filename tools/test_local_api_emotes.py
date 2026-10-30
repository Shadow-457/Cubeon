"""Actual token-authenticated localhost emote routes, wired by FriendsService."""
import http.client
import json
import os
from pathlib import Path
import runpy
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import _sandbox_home
_sandbox_home.isolate()

def main():
    fixtures=runpy.run_path(str(ROOT/'tools/test_friends_service.py'),run_name='emote_api_fixtures')
    service,client,_=fixtures['build']();client.is_connected=True
    now=[100.0]; service.emotes.clock=lambda:now[0]
    api=fixtures['local_api'];service.start();server=api.start._server
    def request(method,route,payload=None,token=None):
        conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
        try:
            conn.request(method,route,None if payload is None else json.dumps(payload),
                         {'Content-Type':'application/json','X-Cubeon-Token':token or server.token})
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()
    try:
        room='a'*64;entity=str(uuid.uuid4());sent=len(client.sent)
        assert request('POST','/emotecontext',{'room':room},'wrong')[0]==401
        assert request('GET','/emotes',token='wrong')[0]==401
        assert len(client.sent)==sent
        assert request('POST','/emotecontext',{'room':room})[1]['ok']
        assert client.sent[-1]==('emote_room',(room,))
        client.fire('emote_ready',{'room':room,'ready':True})
        assert request('GET','/emotes')[1]['ready']
        assert request('POST','/emote',{'uuid':entity,'emote':'wave','serial':1})[1]['ok']
        assert client.sent[-1]==('emote',(entity,'wave',1))
        client.fire('emote',{'room':room,'uuid':entity,'username':'BlueFox','emote':'wave','serial':1,'age':0})
        active=request('GET','/emotes')[1]['active']
        assert len(active)==1 and active[0]['uuid']==entity and active[0]['username']=='BlueFox'
        for serial, emote in enumerate(('clap', 'laugh', 'sit', 'celebrate'), start=2):
            now[0]+=1.0
            assert request('POST','/emote',{'uuid':entity,'emote':emote,'serial':serial})[1]['ok']
            assert client.sent[-1]==('emote',(entity,emote,serial))
            client.fire('emote',{'room':room,'uuid':entity,'username':'BlueFox','emote':emote,'serial':serial,'age':0})
            active=request('GET','/emotes')[1]['active']
            assert len(active)==1 and active[0]['emote']==emote
        assert request('POST','/emote',{'uuid':'bad','emote':'wave','serial':2})[1]['ok'] is False
        service.set_version(None)
        assert request('GET','/emotes')[1]=={'room':'','ready':False,'active':[]}
        assert request('GET','/friends')[0]==200
    finally:service.stop()
    print('Token protection, all new emote send/receive routes, context, invalid input, game-exit cleanup and existing friends route passed.')
    return 0

if __name__=='__main__':sys.exit(main())
