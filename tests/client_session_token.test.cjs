const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
// session.js não toca DOM: carrega isolado com apenas um fetch injetável.
function load(fetchImpl){const context={fetch:fetchImpl,console};vm.createContext(context);vm.runInContext(fs.readFileSync('web/session.js','utf8'),context);return context;}
function reply({status=200,contentType='application/json',body={}}){return{status,headers:{get:(k)=>k.toLowerCase()==='content-type'?contentType:null},json:async()=>body};}

test('fetchSessionToken devolve o csrf_token numa sessão JSON',async()=>{
 const ctx=load(async()=>reply({body:{csrf_token:'abc123'}}));
 assert.equal(await ctx.fetchSessionToken(),'abc123');
});
test('worker não pareado (502 em HTML) vira erro legível, não um crash de JSON.parse',async()=>{
 const ctx=load(async()=>reply({status:502,contentType:'text/html;charset=utf-8',body:undefined}));
 await assert.rejects(()=>ctx.fetchSessionToken(),/make native/);
});
test('outros status sem JSON reportam o código para reconexão',async()=>{
 const ctx=load(async()=>reply({status:503,contentType:'text/plain',body:undefined}));
 await assert.rejects(()=>ctx.fetchSessionToken(),/503/);
});
