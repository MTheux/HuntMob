const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={};vm.createContext(context);vm.runInContext(fs.readFileSync('web/screen-geometry.js','utf8'),context);
test('frame geometry follows portrait and landscape with no fixed iPhone ratio',()=>{
 const values={};const phone={dataset:{},style:{setProperty:(key,value)=>values[key]=value}};const screen={closest:()=>phone};
 context.fitPhoneFrame(screen,648,1440,'android');assert.equal(values['--screen-ratio'],'648 / 1440');assert.equal(phone.dataset.platform,'android');
 context.fitPhoneFrame(screen,1440,648,'android');assert.equal(values['--screen-ratio'],'1440 / 648');
 context.fitPhoneFrame(screen,604,1312,'ios');assert.equal(phone.dataset.platform,'ios');
});
test('missing or invalid frames cannot alter the phone geometry',()=>{
 const phone={dataset:{},style:{setProperty:assert.fail}};
 for(const dims of [[0,2],[-1,1],[NaN,1],[1,Infinity],[9000,10]])context.fitPhoneFrame({closest:()=>phone},...dims,'android');
 context.fitPhoneFrame({closest:()=>null},1,2,'android');
});
