const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/client-validation.js','utf8');
const helper=source.slice(source.indexOf('async function collectClientValidation'),source.indexOf('function clientPlatform'));
function setup(){const c={AbortSignal,Date};vm.createContext(c);vm.runInContext(helper,c);let tick=0;return {c,environment:{now:()=>tick+=10,client:{platform:'iPadOS'},display:()=>({visible:true})}};}
test('measures only same-origin ping and never declares manual journey complete',async()=>{
 const {c,environment}=setup(),routes=[];
 const r=await c.collectClientValidation(async(route)=>{routes.push(route);return {ok:true,json:async()=>({ok:true,version:1})}},environment);
 assert.deepEqual(routes,['/api/client/ping','/api/client/ping','/api/client/ping']);assert.equal(r.connection.median_ms,10);assert.equal(r.connection.state,'connected');assert.equal(r.full_journey_validated,false);assert.equal(r.manual_checks.keyboard,'not_tested');
});
test('identity rejection never becomes successful remote validation',async()=>{
 const {c,environment}=setup();const r=await c.collectClientValidation(async()=>({ok:false,status:403}),environment);assert.equal(r.connection.state,'unreachable');assert.equal(r.connection.median_ms,null);assert.equal(r.connection.errors.length,3);
});
test('partial network failure is retained without URLs or raw error values',async()=>{
 const {c,environment}=setup();let count=0;
 const r=await c.collectClientValidation(async()=>{if(++count===2)throw Error('sensitive URL');return {ok:true,json:async()=>({ok:true,version:1})}},environment);
 assert.equal(r.connection.state,'partial');assert.equal(r.connection.errors[0],'unreachable');assert.ok(!JSON.stringify(r).includes('sensitive'));
});
