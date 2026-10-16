const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const app=fs.readFileSync('web/app.js','utf8');
const sender=app.slice(app.indexOf('let touchQueue ='),app.indexOf('function cancelLiveTouch()'));
test('live input coalesces moves but preserves down/move/up and the original device',async()=>{
  const calls=[];let release;
  const first=new Promise(resolve=>release=resolve);
  const ctx={authorizedPost:async(route,payload)=>{calls.push({route,payload});if(calls.length===1)await first;},notify:assert.fail};
  vm.createContext(ctx);vm.runInContext(sender,ctx);
  const target={route:'/api/ios/action',identity:{udid:'selected-simulator'}};
  const done=ctx.sendLiveTouch({phase:'down',x:0,y:0,target});
  await ctx.sendLiveTouch({phase:'move',x:.1,y:.1,target});
  await ctx.sendLiveTouch({phase:'move',x:.9,y:.9,target});
  await ctx.sendLiveTouch({phase:'up',x:1,y:1,target});
  release();await done;
  assert.deepEqual(calls.map(c=>c.payload.phase),['down','move','up']);
  assert.equal(calls[1].payload.x,.9);
  assert.ok(calls.every(c=>c.route==='/api/ios/action'&&c.payload.udid==='selected-simulator'&&!('target' in c.payload)));
});
test('a second gesture cannot overtake the first release',async()=>{
  const phases=[];let release;const first=new Promise(resolve=>release=resolve);
  const ctx={authorizedPost:async(route,p)=>{phases.push(p.phase);if(phases.length===1)await first;},notify:assert.fail};
  vm.createContext(ctx);vm.runInContext(sender,ctx);
  const target={route:'/api/device/direct-input',identity:{}};
  const done=ctx.sendLiveTouch({phase:'down',target});
  for(const phase of ['up','down','move','up'])await ctx.sendLiveTouch({phase,target});
  release();await done;
  assert.deepEqual(phases,['down','up','down','move','up']);
});
