const {test}=require('node:test'),assert=require('node:assert/strict');
// polling.js é dual CJS/browser (igual workbench-phases.js). everyVisible recebe
// um scheduler injetável para testar o tick sem timers reais.
function load(){delete require.cache[require.resolve('../web/polling.js')];return require('../web/polling.js');}

test('everyVisible chama fn quando a aba está visível',()=>{
 const {everyVisible}=load();let cb;const doc={hidden:false};let calls=0;
 everyVisible(()=>calls++,1000,doc,(fn)=>{cb=fn;return 1;});
 cb();assert.equal(calls,1);
});
test('everyVisible pula fn quando doc.hidden',()=>{
 const {everyVisible}=load();let cb;const doc={hidden:true};let calls=0;
 everyVisible(()=>calls++,1000,doc,(fn)=>{cb=fn;return 1;});
 cb();assert.equal(calls,0);
});
test('everyVisible volta a chamar ao ficar visível de novo',()=>{
 const {everyVisible}=load();let cb;const doc={hidden:true};let calls=0;
 everyVisible(()=>calls++,1000,doc,(fn)=>{cb=fn;return 1;});
 cb();assert.equal(calls,0);doc.hidden=false;cb();assert.equal(calls,1);
});
test('everyVisible devolve o id do scheduler e repassa ms',()=>{
 const {everyVisible}=load();let seenMs;
 const id=everyVisible(()=>{},2500,{hidden:false},(fn,ms)=>{seenMs=ms;return 42;});
 assert.equal(id,42);assert.equal(seenMs,2500);
});
