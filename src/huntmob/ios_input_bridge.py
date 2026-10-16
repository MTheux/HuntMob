"""Private line protocol for the owned Simulator; runs in the packaged idb environment."""
import asyncio
import json
import logging
import sys
from idb.grpc.client import Client
from idb.common.types import DomainSocketAddress, HIDButtonType, HIDDirection, HIDPress, HIDTouch, Point
from idb.grpc.hid import event_to_grpc
from ios_live_touch import LiveTouch

async def main():
    async with Client.build(address=DomainSocketAddress(path=sys.argv[1]),logger=logging.getLogger('huntmob-ios')) as client:
        target=await client.describe()
        if target.udid!=sys.argv[2]: raise ValueError('Simulator mismatch')
        dimensions=target.screen_dimensions
        def touch_event(phase, x, y):
            point=Point(x=x*dimensions.width_points, y=y*dimensions.height_points)
            return event_to_grpc(HIDPress(action=HIDTouch(point=point), direction=HIDDirection.UP if phase in {'up','cancel'} else HIDDirection.DOWN))
        touch=LiveTouch(client,touch_event)
        print(json.dumps({'ok':True,'ready':True}),flush=True)
        try:
          while True:
            line=await asyncio.get_running_loop().run_in_executor(None,sys.stdin.readline)
            if not line: break
            try:
                payload=json.loads(line);action=payload['action']
                if action=='touch':
                    await touch.handle(payload['phase'],payload['x'],payload['y'])
                elif action in {'tap','swipe'}:
                    await touch.close()
                    keys=['x','y'] if action=='tap' else ['x','y','end_x','end_y']
                    values=[int(round(payload[key]*(dimensions.width_points if index%2==0 else dimensions.height_points))) for index,key in enumerate(keys)]
                    if action=='tap': await client.tap(*values)
                    else: await client.swipe(tuple(values[:2]),tuple(values[2:]),duration=.25,delta=10)
                elif action in {'home','lock'}:
                    await client.button({'home':HIDButtonType.HOME,'lock':HIDButtonType.LOCK}[action])
                elif action=='recents':
                    await client.button(HIDButtonType.HOME)
                    await client.button(HIDButtonType.HOME)
                elif action=='key':await client.key({'Backspace':42,'Enter':40,'Tab':43,'ArrowUp':82,'ArrowDown':81,'ArrowLeft':80,'ArrowRight':79}[payload['key']])
                elif action=='text':await client.text(payload['text'])
                else:raise ValueError('Unsupported action')
                print(json.dumps({'ok':True}),flush=True)
            except Exception:
                print(json.dumps({'ok':False,'reason':'Simulator recusou a entrada.'}),flush=True)
        finally:
            await touch.close()

asyncio.run(main())
