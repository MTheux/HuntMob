const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/app.js','utf8');
const context={URL,validPackage:value=>/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/.test(value)};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function playPackage('),source.indexOf('function updateLabSource(')),context);
test('accepts official store links without fetching and extracts only package',()=>{
 assert.equal(context.playPackage('https://play.google.com/store/apps/details?id=com.example.app&hl=pt_BR'),'com.example.app');
 assert.equal(context.playPackage(' com.example.app '),'com.example.app');
 assert.equal(context.playPackage(''),'');
});
test('rejects foreign hosts, credentials, duplicate IDs and unsafe package input',()=>{
 for(const value of ['https://play.google.com.evil.test/store/apps/details?id=com.example.app','https://user:pass@play.google.com/store/apps/details?id=com.example.app','http://play.google.com/store/apps/details?id=com.example.app','https://play.google.com/store/apps/details?id=com.example.app&id=com.other.app','https://play.google.com/store/apps/details?id=--help','https://play.google.com/store/apps','--help'])assert.throws(()=>context.playPackage(value));
});
