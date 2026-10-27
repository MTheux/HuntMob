const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const helper=source.slice(source.indexOf('let dastConnection={};'),source.indexOf('function renderDastTarget'));
function setup(fetch){
  const lab={id:'lab',package_id:'com.lab.fixture',apk_sha256:'a'.repeat(64),root_mode:'stock'};
  const c={devicePlatform:'android',runtimeDevice:{state:'on'},activeLab:lab,dynamicBusy:false,targetBindingBusy:false,dynamicSessionActive:false,
    AbortSignal,dastAppPicker:{sync(){}},window:{huntmobDastApps:{sync(){}}},fetch};
  c.dastTarget=()=>({...c.activeLab,available:true});c.dastQuery=()=>'';
  vm.createContext(c);vm.runInContext(helper+'\nthis.currentDastConnection=currentDastConnection;',c);return {c,lab};
}
test('connection checks are read only and a blocked result is cached until explicit recheck',async()=>{
  const calls=[];let lab;
  const r=setup(async(route,options)=>{calls.push({route,options});return {ok:true,json:async()=>({lab_id:lab.id,package_id:lab.package_id,apk_sha256:lab.apk_sha256,ready:false,reason:'Gadget indisponível.'})};});
  lab=r.lab;await r.c.refreshDastConnection();await r.c.refreshDastConnection();assert.equal(calls.length,1);
  assert.equal(calls[0].route,'/api/dynamic/readiness');assert.equal(calls[0].options.method,undefined);
  assert.equal(r.c.currentDastConnection().ready,false);assert.equal(r.c.currentDastConnection().checked,true);
  await r.c.refreshDastConnection(true);assert.equal(calls.length,2);
});
test('late readiness from another APK cannot enable the current target',async()=>{
  let resolve;const pending=new Promise(done=>resolve=done);
  const {c,lab}=setup(()=>pending);const checking=c.refreshDastConnection();
  c.activeLab={...lab,package_id:'com.lab.other',apk_sha256:'b'.repeat(64)};
  resolve({ok:true,json:async()=>({lab_id:lab.id,package_id:lab.package_id,apk_sha256:lab.apk_sha256,ready:true})});
  await checking;assert.equal(c.currentDastConnection().ready,undefined);
});
test('concurrent connection checks share the pending request and failures stay blocked',async()=>{
  let reject,calls=0;const pending=new Promise((_,fail)=>reject=fail);
  const {c}=setup(()=>{calls++;return pending;});const checking=c.refreshDastConnection();
  await c.refreshDastConnection(true);assert.equal(calls,1);
  reject(Error('Worker indisponível'));await checking;
  assert.equal(c.currentDastConnection().ready,false);assert.equal(c.currentDastConnection().loading,false);
});

test('readiness from the original Android cannot enable its companion',async()=>{
  let resolve;const pending=new Promise(done=>resolve=done);
  const {c,lab}=setup(()=>pending);const checking=c.refreshDastConnection();
  const child={...lab,id:'child',root_mode:'root'};c.dastTarget=()=>({...child,available:true});
  resolve({ok:true,json:async()=>({lab_id:lab.id,package_id:lab.package_id,apk_sha256:lab.apk_sha256,ready:true})});
  await checking;assert.equal(c.currentDastConnection().ready,undefined);
});
