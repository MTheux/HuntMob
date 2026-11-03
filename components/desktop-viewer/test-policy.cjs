const {test}=require('node:test'),assert=require('node:assert/strict'),{workerUrl,protocolUrl,localWorkerReady}=require('./policy.cjs');
test('local worker and private HTTPS accepted',()=>{assert.equal(new URL(workerUrl('http://127.0.0.1:8090/')).searchParams.get('viewer'),'1');assert.equal(new URL(workerUrl('https://worker.tail123.ts.net:8443/?platform=ios')).searchParams.get('platform'),'ios');});
test('external, credential and script URLs rejected',()=>{for(const value of ['javascript:alert(1)','https://outside.test/','http://worker.tail123.ts.net/','https://user:pass@worker.tail123.ts.net/','http://localhost:8090/api/session','http://localhost:8090/?token=secret'])assert.throws(()=>workerUrl(value));});
test('custom protocol validates destination',()=>{assert.match(protocolUrl('huntmob-viewer://open?url='+encodeURIComponent('http://localhost:8090/?platform=android')),/platform=android/);assert.throws(()=>protocolUrl('huntmob-viewer://open?url='+encodeURIComponent('https://outside.test/')));});
test('local viewer opens directly only when the loopback gateway has no operator prompt',async()=>{
 const ready=await localWorkerReady(async url=>{assert.equal(url,'http://127.0.0.1:8090/api/auth/status');return {ok:true,json:async()=>({ok:true,authenticated:true,operator:false})};});
 assert.equal(ready,true);
 for(const status of [{ok:true,authenticated:false,operator:false},{ok:true,authenticated:true},{ok:false,authenticated:true,operator:false}])
  assert.equal(await localWorkerReady(async()=>({ok:true,json:async()=>status})),false);
 assert.equal(await localWorkerReady(async()=>{throw Error('offline');}),false);
});
