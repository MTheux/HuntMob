const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/operator-session.js','utf8');
function setup({token='f'.repeat(64),holdBootstrap=false,localTrusted=false}={}){
 const elements=[],events={},calls=[],storage=new Map();let cleared=false,release;
 function element(tag){const e={tag,children:[],className:'',value:'',append(...children){this.children.push(...children);},setAttribute(){},addEventListener(name,fn){this[name]=fn;},showModal(){this.open=true;},close(){this.open=false;}};elements.push(e);return e;}
 const document={createElement:element,body:element('body'),addEventListener:(name,fn)=>events[name]=fn};
 const context={URL,URLSearchParams,Headers,Request,console,location:{hash:token?'#operator='+token:'',pathname:'/',search:'',origin:'http://127.0.0.1:8090',href:'http://127.0.0.1:8090/'},history:{replaceState(){cleared=true;}},document,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},window:{}};
 context.window.fetch=async(input,options={})=>{
  const route=String(input);calls.push({route,options,fragmentCleared:cleared});
  if(route==='/api/auth/bootstrap'){
   if(holdBootstrap)await new Promise(resolve=>release=resolve);
   return {ok:true,status:200,json:async()=>({authenticated:true,proof:'fixture-proof'})};
  }
  if(route==='/api/auth/status')return {ok:true,status:200,json:async()=>localTrusted?({authenticated:true,operator:false}):({authenticated:false})};
  if(route.startsWith('/api/auth/ticket?'))return {ok:true,status:200,json:async()=>({ticket:'fixture-ticket'})};
  return {ok:true,status:200,json:async()=>({ok:true})};
 };
 vm.createContext(context);vm.runInContext(source,context);
 return {context,calls,elements,storage,events,release:()=>release?.()};
}
test('API initialization waits for bootstrap and carries independent operator proof',async()=>{
 const f=setup({holdBootstrap:true}),pending=f.context.window.fetch('/api/session');
 await Promise.resolve();assert.equal(f.calls.length,1);assert.equal(f.calls[0].fragmentCleared,true);
 f.release();await pending;
 assert.equal(f.calls.at(-1).route,'/api/session');
 assert.equal(f.calls.at(-1).options.headers.get('X-HuntMob-Operator'),'fixture-proof');
 assert.equal(f.storage.get('huntmob.operatorProof'),'fixture-proof');
});
test('missing launch credentials fail closed without rendering a connect screen',async()=>{
 const f=setup({token:null});
 await assert.rejects(()=>f.context.window.fetch('/api/evidence'),/Sessão de operador indisponível/);
 assert.equal(f.calls.some(c=>c.route==='/api/evidence'),false);
 assert.equal(f.elements.some(e=>e.tag==='dialog'),false);
 assert.equal(f.elements.some(e=>e.tag==='input'),false);
});
test('trusted Docker loopback skips the private-address dialog and calls the API directly',async()=>{
 const f=setup({token:null,localTrusted:true});
 await f.context.window.fetch('/api/session');
 assert.equal(f.elements.some(e=>e.tag==='dialog'),false);
 assert.deepEqual(f.calls.map(call=>call.route),['/api/auth/status','/api/session']);
 assert.equal(f.calls.at(-1).options.headers,undefined);
 assert.equal(f.storage.get('huntmob.operatorProof'),undefined);
});
test('read tickets bind the requested path and proof is never attached to a foreign origin',async()=>{
 const f=setup();
 const url=new URL(await f.context.window.huntmobOperator.mediaUrl('/api/dynamic/report.json?device=owned'));
 const call=f.calls.find(c=>c.route.startsWith('/api/auth/ticket?'));
 assert.equal(new URL(call.route,'http://127.0.0.1:8090').searchParams.get('path'),'/api/dynamic/report.json?device=owned');
 assert.equal(call.options.headers['X-HuntMob-Operator'],'fixture-proof');
 assert.equal(url.searchParams.get('_operator_ticket'),'fixture-ticket');
 await f.context.window.fetch('https://example.test/public');
 assert.equal(f.calls.at(-1).options.headers,undefined);
 const event={target:{closest:()=>({href:url.href})},preventDefault(){throw Error('Ticket link must not be wrapped again');}};
 await f.events.click(event);
});
