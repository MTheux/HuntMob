const {test}=require('node:test'),assert=require('node:assert/strict');
const {present,duration,actions}=require('../web/dast-progress.js');
const receipt={id:'dyn_fixture',lab_id:'child',started_epoch:1000};
const running={state:'running',receipt};

test('collection percentage measures its time window and shows elapsed and remaining',()=>{
  const view=present({snapshot:running,now:1180});
  assert.equal(view.value,10);assert.equal(view.time,'03:00');assert.equal(view.remaining,'27:00');
  assert.equal(view.kind,'collecting');assert.match(view.percentage,/janela de tempo/);
  assert.match(view.detail,/sem medir a cobertura/);
});
test('the deadline never pretends the report or interactive testing finished',()=>{
  assert.equal(present({snapshot:running,now:2799.9}).value,99);
  const deadline=present({snapshot:running,now:2800});
  assert.equal(deadline.value,100);assert.equal(deadline.remaining,'00:00');assert.equal(deadline.kind,'limit');
  assert.equal(deadline.steps[2],'pending');assert.match(deadline.detail,/Encerrar e analisar/);
  assert.equal(present({snapshot:running,now:99999}).remaining,'00:00');
});
test('a volume limit is visible even when the time window has remaining time',()=>{
  const view=present({snapshot:{...running,receipt:{...receipt,dropped_event_count:2}},now:1030});
  assert.equal(view.kind,'limit');assert.equal(view.remaining,'29:30');assert.match(view.detail,/volume/);
});
test('closed session time freezes at the actual end and only its report can complete it',()=>{
  const snapshot={state:'stopped',receipt:{...receipt,ended_epoch:1123}};
  const pending=present({snapshot,now:9999});assert.equal(pending.time,'02:03');assert.equal(pending.kind,'stopped');
  const unrelated=present({snapshot,report:{job_id:'dyn_other',lab_id:'child'},now:9999});assert.equal(unrelated.kind,'stopped');
  const foreign=present({snapshot,report:{job_id:receipt.id,lab_id:'parent'},now:9999});assert.equal(foreign.kind,'stopped');
  const done=present({snapshot,report:{job_id:receipt.id,lab_id:receipt.lab_id},now:9999});
  assert.equal(done.kind,'complete');assert.equal(done.value,100);assert.equal(done.time,'02:03');
});
test('analyzing active evidence produces a partial report while collection continues',()=>{
  const view=present({snapshot:running,report:{job_id:receipt.id,lab_id:receipt.lab_id},now:1180});
  assert.equal(view.kind,'collecting');assert.equal(view.value,10);assert.equal(view.steps[2],'partial');assert.match(view.detail,/Relatório parcial/);
});
test('unknown operation duration stays indeterminate and only one step is current',()=>{
  for(const action of ['start','stop','analyze','prepare','capture']){
    const view=present({snapshot:running,operation:{action,started:1200},now:1207});
    assert.equal(view.value,null);assert.equal(view.indeterminate,true);assert.equal(view.remaining,'Sem estimativa');assert.equal(view.time,'00:07');
    assert.equal(view.steps.filter(state=>state==='current').length,1);
  }
});
test('malformed or missing times never display NaN or keep counting an interrupted session',()=>{
  for(const state of ['idle','failed','interrupted','detached']){
    const view=present({snapshot:{state,receipt:{...receipt,started_epoch:NaN}},now:2000});
    assert.equal(view.time,'—');assert.doesNotMatch(JSON.stringify(view),/NaN/);
  }
  assert.equal(present({snapshot:{state:'running',receipt:{...receipt,started_epoch:2000}},now:1000}).time,'00:00');
  assert.equal(duration(3661),'61:01');
});
test('ISO receipts and explicit server limits remain measurable',()=>{
  const view=present({snapshot:{state:'running',receipt:{id:'dyn',started_at:'2026-01-01T00:00:00Z',max_session_seconds:600}},now:Date.parse('2026-01-01T00:05:00Z')/1000});
  assert.equal(view.value,50);assert.equal(view.remaining,'05:00');assert.match(view.detail,/10:00/);
});
test('loss of worker status cannot keep claiming a current collection state',()=>{
  const view=present({snapshot:running,error:'Worker indisponível',now:1180});
  assert.equal(view.kind,'error');assert.equal(view.value,null);assert.equal(view.indeterminate,false);
});
test('active collection exposes stop, partial analysis, capture and export without a second start',()=>{
  const view=actions({active:true,available:true,identified:true,hasReceipt:true});
  assert.equal(view.showStart,false);assert.equal(view.showStop,true);assert.equal(view.stopEnabled,true);
  assert.equal(view.analyzeEnabled,true);assert.equal(view.exportEnabled,true);assert.equal(view.captureEnabled,true);
  assert.equal(view.analyzeLabel,'Gerar análise parcial');assert.match(view.help,/Sessão ativa/);
});
test('operation loading disables conflicting actions and an absent receipt cannot be exported',()=>{
  const busy=actions({active:true,busy:true,available:true,identified:true,hasReceipt:true});
  for(const key of ['stopEnabled','analyzeEnabled','captureEnabled','exportEnabled'])assert.equal(busy[key],false);
  const idle=actions({available:true,identified:true});assert.equal(idle.analyzeEnabled,false);assert.equal(idle.exportEnabled,false);assert.equal(idle.showStop,false);
});
test('offline devices can analyze saved evidence but cannot capture or start',()=>{
  const view=actions({available:false,identified:true,hasReceipt:true,canStart:true});
  assert.equal(view.analyzeEnabled,true);assert.equal(view.exportEnabled,true);assert.equal(view.captureEnabled,false);assert.equal(view.startEnabled,false);
});

const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync('web/app.js','utf8');
const actionSource=source.slice(source.indexOf('async function dynamicAction('),source.indexOf("runFrida.addEventListener('click'"));
function actionHarness(post){
  const nodes=new Map(),reports=[];
  const context={dynamicBusy:false,targetBindingBusy:false,dastDeviceId:'child',dynamicError:'',dastProgressError:'',dastProgressOperation:undefined,
    dastAppPicker:{state:()=>({canStart:true})},dastTarget:()=>({id:'child',package_id:'com.lab.child'}),dastPayload:()=>({workspace_id:'parent',device_id:'child'}),
    updateDastProgress(){},window:{huntmobDastApps:{sync(){}}},scriptOptions:[],observerIds:['tls-observe'],packageId:{value:'com.lab.parent'},
    document:{querySelector(id){if(!nodes.has(id))nodes.set(id,{value:'spawn',textContent:'',disabled:false,hidden:false,replaceChildren(){}});return nodes.get(id);}},
    authorizedPost:post,notify(){},loadEvidence(){},renderNativeReport:r=>reports.push(r),clearReportDetails(){},nativeReportJob:'',fridaConsole:{textContent:''},
    dastConnection:{},dastConnectionKey:()=>'',refreshDynamic:async()=>{},Date};
  vm.createContext(context);vm.runInContext(actionSource,context);return {context,reports,nodes};
}
test('analysis, stop and capture use the selected companion and its package',async()=>{
  const calls=[],h=actionHarness(async(route,payload)=>{calls.push({route,payload});return {report:{lab_id:'child'}};});
  for(const action of ['analyze','stop','capture'])await h.context.dynamicAction(action,true);
  assert.equal(calls.length,3);
  for(const {route,payload} of calls){assert.equal(route,'/api/dynamic');assert.equal(payload.device_id,'child');assert.equal(payload.workspace_id,'parent');assert.equal(payload.package_id,'com.lab.child');assert.equal(payload.include_proxy,false);}
  assert.equal(h.context.dynamicBusy,false);assert.equal(h.context.dastProgressOperation,undefined);
});
test('a late operation cannot render its report into another selected device',async()=>{
  let resolve;const waiting=new Promise(done=>resolve=done),h=actionHarness(()=>waiting);
  const pending=h.context.dynamicAction('analyze',true);h.context.dastTarget=()=>({id:'other'});
  resolve({report:{lab_id:'child'}});await pending;
  assert.equal(h.reports.length,0);assert.equal(h.context.dynamicBusy,false);
});
test('an operation error clears loading so the analyst can retry',async()=>{
  const h=actionHarness(async()=>{throw Error('fixture worker error');});
  await h.context.dynamicAction('analyze',true);
  assert.equal(h.context.dynamicBusy,false);assert.equal(h.context.dastProgressOperation,undefined);assert.equal(h.nodes.get('#analyzeDast').disabled,false);
});
