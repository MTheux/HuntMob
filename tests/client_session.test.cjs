const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/app.js','utf8');const helper=source.slice(source.indexOf('async function sessionFetch'),source.indexOf('async function authorizedPost'));
function response(status,payload,type='application/json'){return {status,headers:{get:()=>type},clone(){return this},async json(){return payload}};}
test('stale CSRF rejected before execution is renewed exactly once',async()=>{
 const sent=[];let changes=0;
 const context={csrfToken:'old',fetch:async(route,options)=>{if(route==='/api/session')return response(200,{csrf_token:'new'});sent.push(options.headers['X-HuntMob-CSRF']);if(sent.length===1)return response(403,{error_code:'csrf_session_changed',executed:false});changes++;return response(200,{ok:true})}};
 vm.createContext(context);vm.runInContext(helper,context);const result=await context.sessionFetch('/api/device/action',{method:'POST',headers:{},body:'owned'});
 assert.equal(result.status,200);assert.deepEqual(sent,['old','new']);assert.equal(changes,1);
});
test('authorization rejection and uncertain execution are never replayed',async()=>{
 for(const payload of [{error_code:'access_denied',executed:false},{error_code:'csrf_session_changed',executed:true}]){
  let count=0;const context={csrfToken:'old',fetch:async()=>{count++;return response(403,payload)}};vm.createContext(context);vm.runInContext(helper,context);
  assert.equal((await context.sessionFetch('/api/device/action',{method:'POST'})).status,403);assert.equal(count,1);
 }
});
test('network errors do not retry a potentially executed mutation',async()=>{
 let count=0;const context={csrfToken:'old',fetch:async()=>{count++;throw Error('connection lost')}};vm.createContext(context);vm.runInContext(helper,context);
 await assert.rejects(()=>context.sessionFetch('/api/device/action',{method:'POST'}),/connection lost/);assert.equal(count,1);
});
test('HTML error becomes an actionable message, not JSON parse failure',async()=>{
 const context={csrfToken:'old',fetch:async()=>response(502,{},'text/html')};vm.createContext(context);vm.runInContext(helper,context);
 await assert.rejects(()=>context.sessionFetch('/api/device/action',{method:'POST'}),/502/);
});
