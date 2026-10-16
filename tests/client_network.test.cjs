const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/app.js','utf8');const helper=source.slice(source.indexOf('async function loadNetwork()'),source.indexOf("document.querySelector('#openProxyWeb').addEventListener('click', loadNetwork)"));
function setup(){
 const fields={'#sendStatus':{textContent:'Aguardando resposta'},'#networkStats':{textContent:''},'#requestEditor':{value:'draft edited by user'}};
 const completed={id:'flow',state:'response',status:200,response:{body:'owned lab response'}};let rendered;
 const c={networkLoading:false,detailEpoch:1,networkRenderSignature:'previous',networkSelection:{id:'flow',state:'pending'},networkFlows:[],replayBusy:false,document:{querySelector:s=>fields[s]},fetch:async()=>({ok:true,json:async()=>({flows:[completed]})}),renderResponse:(...args)=>{rendered=args;},renderNetwork:()=>{}};
 vm.createContext(c);vm.runInContext(helper,c);return {c,fields,rendered:()=>rendered};
}
test('completed capture updates pending response and preserves edited request',async()=>{
 const {c,fields,rendered}=setup();await c.loadNetwork();assert.equal(rendered()[1],200);assert.equal(fields['#sendStatus'].textContent,'Resposta capturada');assert.equal(fields['#requestEditor'].value,'draft edited by user');
});
test('polling never replaces explicit Send result',async()=>{
 const {c,fields,rendered}=setup();fields['#sendStatus'].textContent='200 · 2 ms';await c.loadNetwork();assert.equal(rendered(),undefined);assert.equal(fields['#sendStatus'].textContent,'200 · 2 ms');
});
test('transient fetch failure invalidates cached render so next success clears error',async()=>{
 const {c,fields}=setup();c.fetch=async()=>{throw Error('connection interrupted')};await c.loadNetwork();assert.equal(c.networkRenderSignature,'');assert.equal(fields['#networkStats'].textContent,'connection interrupted');assert.equal(c.networkLoading,false);
});
