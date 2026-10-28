const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
// fetchJson mora em web/session.js (classic script). Carrega o módulo num
// contexto vm com um fetch injetável, igual aos demais testes de cliente.
const source=fs.readFileSync('web/session.js','utf8');
function load(fetchStub){const context={fetch:fetchStub};vm.createContext(context);vm.runInContext(source,context);return context;}
function res(status,payload,type='application/json'){return {status,headers:{get:()=>type},async json(){return payload}};}

test('fetchJson devolve o corpo JSON quando o content-type é application/json',async()=>{
 const ctx=load(async()=>res(200,{ok:true,value:42}));
 assert.deepEqual(await ctx.fetchJson('/api/x'),{ok:true,value:42});
});
test('fetchJson devolve corpo JSON mesmo em resposta de erro (ok:false)',async()=>{
 const ctx=load(async()=>res(400,{ok:false,reason:'ruim'}));
 assert.deepEqual(await ctx.fetchJson('/api/x'),{ok:false,reason:'ruim'});
});
test('fetchJson transforma HTML 502 (worker não pareado) em mensagem acionável',async()=>{
 const ctx=load(async()=>res(502,{},'text/html'));
 await assert.rejects(()=>ctx.fetchJson('/api/x'),/make native/);
});
test('fetchJson transforma HTML de outro status em mensagem com o código',async()=>{
 const ctx=load(async()=>res(503,{},'text/html'));
 await assert.rejects(()=>ctx.fetchJson('/api/x'),/503/);
});
test('fetchJson é defensivo: sem headers.get no stub, apenas faz o parse',async()=>{
 const ctx=load(async()=>({status:200,async json(){return {ok:true}}}));
 assert.deepEqual(await ctx.fetchJson('/api/x'),{ok:true});
});
test('fetchJson repassa input e init ao fetch',async()=>{
 let seen;const ctx=load(async(input,init)=>{seen={input,init};return res(200,{ok:true})});
 await ctx.fetchJson('/api/y',{method:'POST',cache:'no-store'});
 assert.equal(seen.input,'/api/y');assert.deepEqual(seen.init,{method:'POST',cache:'no-store'});
});
test('fetchSessionToken reaproveita fetchJson e devolve o csrf_token',async()=>{
 const ctx=load(async()=>res(200,{csrf_token:'abc'}));
 assert.equal(await ctx.fetchSessionToken(),'abc');
});

test('fetchJsonOk devolve o corpo quando response.ok',async()=>{
 const ctx=load(async()=>({status:200,ok:true,headers:{get:()=>'application/json'},async json(){return {ok:true,v:7}}}));
 assert.deepEqual(await ctx.fetchJsonOk('/api/x',undefined,'X'),{ok:true,v:7});
});
test('fetchJsonOk lança body.reason em 400 com corpo JSON',async()=>{
 const ctx=load(async()=>({status:400,ok:false,headers:{get:()=>'application/json'},async json(){return {reason:'ação recusada'}}}));
 await assert.rejects(()=>ctx.fetchJsonOk('/api/x',undefined,'X'),/ação recusada/);
});
test('fetchJsonOk lança mensagem acionável em 502 HTML (worker não pareado)',async()=>{
 const ctx=load(async()=>({status:502,ok:false,headers:{get:()=>'text/html'},async json(){return {}}}));
 await assert.rejects(()=>ctx.fetchJsonOk('/api/x',undefined,'X'),/make native/);
});
test('fetchJsonOk usa label+status quando não há reason',async()=>{
 const ctx=load(async()=>({status:503,ok:false,headers:{get:()=>'application/json'},async json(){return {}}}));
 await assert.rejects(()=>ctx.fetchJsonOk('/api/x',undefined,'runtime'),/runtime 503/);
});
