const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('local UI never opens operator form or requests a bootstrap URL',async()=>{
 const calls=[];
 const context={
  URL,
  location:{origin:'http://127.0.0.1:8090'},
  window:{fetch:async path=>{calls.push(path);throw Error('unexpected fetch');}},
  document:{createElement:()=>{throw Error('unexpected dialog');}},
 };
 vm.createContext(context);
 vm.runInContext(fs.readFileSync('web/operator-session.js','utf8'),context);
 assert.equal(await context.window.huntmobOperator.mediaUrl('/api/device/stream?t=1'),
  'http://127.0.0.1:8090/api/device/stream?t=1');
 assert.deepEqual(calls,[]);
 await assert.rejects(()=>context.window.huntmobOperator.mediaUrl('https://other.example/api/device/stream'),
  /Endereço de mídia inválido/);
});
