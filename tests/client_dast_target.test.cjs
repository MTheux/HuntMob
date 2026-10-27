const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {create}=require('../web/dast-target.js');
const APP='com.lab.fixture',OTHER='com.lab.other';
function setup(overrides={}) {
  const context={labId:'lab-a',available:true,packageId:'',sha256:'',busy:false,active:false,connectionReady:true};
  const selected=[],views=[];
  const picker=create({context:()=>context,list:async()=>[OTHER,APP,APP,'not a package','<script>'],
    bind:async app=>{selected.push(app);context.packageId=app;context.sha256='a'.repeat(64);return true;},
    onChange:view=>views.push(view),...overrides});
  return {context,picker,selected,views};
}
function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};}
test('installed apps are deduplicated and selection waits for identified APK before start',async()=>{
  const r=setup();assert.equal(r.picker.state().canStart,false);
  await r.picker.load();assert.deepEqual(r.picker.state().apps,[APP,OTHER]);
  assert.equal(await r.picker.choose('com.lab.uninstalled'),false);assert.deepEqual(r.selected,[]);
  assert.equal(await r.picker.choose(APP),true);assert.deepEqual(r.selected,[APP]);
  assert.equal(r.picker.state().canStart,true);
  r.context.sha256='';assert.equal(r.picker.state().canStart,false);
});
test('in-flight identification blocks input and failed binding never enables start',async()=>{
  const pending=deferred();const r=setup({bind:()=>pending.promise});await r.picker.load();
  const result=r.picker.choose(APP);assert.equal(r.picker.state().disabled,true);assert.equal(r.picker.state().canStart,false);
  assert.equal(await r.picker.choose(OTHER),false);pending.resolve(false);
  assert.equal(await result,false);assert.equal(r.picker.state().canStart,false);assert.ok(r.picker.state().error);
});
test('a late app list cannot populate a different lab or replace its new request',async()=>{
  const requests=[deferred(),deferred()];let index=0;
  const r=setup({list:()=>requests[index++].promise});const old=r.picker.load();
  r.context.labId='lab-b';const fresh=r.picker.load();
  requests[0].resolve([APP]);assert.equal(await old,false);assert.equal(r.picker.state().loading,true);
  requests[1].resolve([OTHER]);assert.equal(await fresh,true);assert.deepEqual(r.picker.state().apps,[OTHER]);
});
test('disconnect or lab switch invalidates an in-flight selection',async()=>{
  for(const next of [{labId:'lab-b'},{available:false}]){
    const pending=deferred();const r=setup({bind:()=>pending.promise});await r.picker.load();
    const result=r.picker.choose(APP);Object.assign(r.context,next);r.picker.sync();pending.resolve(true);
    assert.equal(await result,false);assert.equal(r.picker.state().canStart,false);assert.deepEqual(r.picker.state().apps,[]);
  }
});
test('running session and an app already bound to the lab prevent target changes',async()=>{
  const r=setup();await r.picker.load();r.context.active=true;
  assert.equal(await r.picker.choose(APP),false);assert.deepEqual(r.selected,[]);
  r.context.active=false;await r.picker.choose(APP);
  assert.equal(await r.picker.choose(OTHER),false);assert.deepEqual(r.selected,[APP]);
  assert.match(r.picker.state().error,/outro lab/);
});
test('opening an active companion still loads its inventory without changing the target',async()=>{
  const r=setup();Object.assign(r.context,{active:true,packageId:APP,sha256:'a'.repeat(64)});
  assert.equal(r.picker.state().refreshDisabled,false);
  assert.equal(await r.picker.load(),true);
  assert.deepEqual(r.picker.state().apps,[APP,OTHER]);assert.equal(r.picker.state().browseOnly,true);
  assert.equal(r.picker.state().canStart,false);
  assert.equal(await r.picker.choose(OTHER),false);assert.equal(await r.picker.choose(APP),false);
  assert.deepEqual(r.selected,[]);assert.equal(r.context.packageId,APP);
});
test('refreshing the inventory remains single-flight during a running session',async()=>{
  const pending=deferred();let calls=0;const r=setup({list:()=>{calls++;return pending.promise;}});
  r.context.active=true;const first=r.picker.load();
  assert.equal(r.picker.state().loading,true);assert.equal(r.picker.state().browseOnly,false);
  assert.equal(await r.picker.load(),false);assert.equal(calls,1);
  pending.resolve([APP]);assert.equal(await first,true);assert.deepEqual(r.picker.state().apps,[APP]);
});
test('active-session list failure remains visible and retryable',async()=>{
  let fail=true;const r=setup({list:async()=>{if(fail)throw Error('inventory fixture unavailable');return [APP];}});
  Object.assign(r.context,{active:true,packageId:APP});
  assert.equal(await r.picker.load(),false);assert.equal(r.picker.state().refreshDisabled,false);
  assert.match(r.picker.state().error,/unavailable/);fail=false;
  assert.equal(await r.picker.load(),true);assert.equal(r.picker.state().error,'');
});
test('an identified APK cannot start DAST before the Frida connection preflight passes',async()=>{
  const r=setup();await r.picker.load();await r.picker.choose(APP);
  for(const value of [undefined,false]){r.context.connectionReady=value;assert.equal(r.picker.state().canStart,false);}
  r.context.connectionReady=true;assert.equal(r.picker.state().canStart,true);
});
test('list failures remain recoverable and empty devices do not enable start',async()=>{
  let fail=true;const r=setup({list:async()=>{if(fail)throw Error('Worker indisponível');return [];}});
  assert.equal(await r.picker.load(),false);assert.equal(r.picker.state().refreshDisabled,false);assert.match(r.picker.state().error,/Worker/);
  fail=false;assert.equal(await r.picker.load(),true);assert.equal(r.picker.state().error,'');assert.equal(r.picker.state().canStart,false);
});
test('global app binding cannot overwrite the UI of a lab selected during APK extraction',async()=>{
  const pending=deferred(),fields={'#targetAppState':{textContent:''}};
  const c={activeLab:{id:'lab-a'},devicePlatform:'android',targetBindingBusy:false,currentSelectedPackage:'',
    refreshFridaSelection(){},deviceAction:()=>pending.promise,document:{querySelector:selector=>fields[selector]}};
  const source=fs.readFileSync('web/app.js','utf8');
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function selectApp('),source.indexOf('async function loadInstalledApps()')),c);
  const result=c.selectApp(APP,true);c.activeLab={id:'lab-b'};pending.resolve({lab:{id:'lab-a',package_id:APP}});
  assert.equal(await result,false);assert.equal(c.activeLab.id,'lab-b');assert.equal(c.currentSelectedPackage,'');assert.equal(c.targetBindingBusy,false);
});
test('the bound package is visible before an active sessions inventory finishes loading',()=>{
  const source=fs.readFileSync('web/app.js','utf8'),nodes=new Map();
  const select={options:[],replaceChildren(...options){this.options=options;},add(option){this.options.push(option);},
    set value(value){this.selected=this.options.some(o=>o.value===value)?value:'';},get value(){return this.selected;}};
  nodes.set('#dastAppSelect',select);
  const c={dynamicBusy:false,targetBindingBusy:false,dastAppSignature:'',currentDastConnection:()=>({}),
    dastProgressScope:'child',dastProgressData:{receipt:{lab_id:'child'}},dastQuery:()=>'?workspace=parent&device=child',window:{huntmobDastProgress:require('../web/dast-progress.js')},
    Option:class {constructor(text,value){this.text=text;this.value=value;}},document:{querySelector(id){if(!nodes.has(id))nodes.set(id,{dataset:{},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];}});return nodes.get(id);}}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function renderDastTarget('),source.indexOf('const dastAppPicker=')),c);
  c.renderDastTarget({scope:'child',apps:[],packageId:APP,available:true,active:true,disabled:true,browseOnly:true});
  assert.equal(select.value,APP);assert.equal(select.options.find(o=>o.value===APP).text,APP);assert.equal(select.disabled,false);
  c.renderDastTarget({scope:'child',apps:[APP,OTHER],packageId:APP,available:true,active:true,disabled:true,browseOnly:true});
  assert.equal(select.value,APP);assert.equal(select.options.find(o=>o.value===OTHER).disabled,true);
  assert.equal(nodes.get('#startDast').hidden,true);assert.equal(nodes.get('#stopDast').hidden,false);assert.equal(nodes.get('#stopDast').disabled,false);
  assert.equal(nodes.get('#analyzeDast').textContent,'Gerar análise parcial');
});
test('automatic inventory loading runs for active DAST without another Frida preflight',()=>{
  const source=fs.readFileSync('web/app.js','utf8');let loads=0,checks=0;
  const c={window:{},dastTarget:()=>({available:true}),dastAppPicker:{sync:()=>({available:true,busy:false,active:true,attempted:false,packageId:APP}),load:()=>{loads++;}},
    refreshDastConnection:()=>{checks++;},document:{querySelector:()=>({classList:{contains:()=>true}})}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('window.huntmobDastApps={'),source.indexOf("document.querySelector('#checkDastConnection').addEventListener")),c);
  c.window.huntmobDastApps.sync();assert.equal(loads,1);assert.equal(checks,0);
});
