const test=require('node:test');
const assert=require('node:assert/strict');
const support=require('../web/tool-support.js');
const fs=require('node:fs'),vm=require('node:vm');
test('iOS keeps implemented tools and distinguishes Android-only and experimental tools',()=>{
  for(const tab of ['device-tools','reverse','proxy','evidence'])assert.equal(support.tab(tab,true).state,'supported');
  for(const tab of ['files','dast'])assert.equal(support.tab(tab,true).state,'android');
  assert.equal(support.tab('frida',true).state,'experimental');
  for(const tab of ['files','dast','frida'])assert.equal(support.tab(tab,false).state,'supported');
});
test('iOS controls hide Android drivers while preserving native Simulator actions',()=>{
  for(const button of [{id:'quickRoot',dataset:{}},{dataset:{panel:'camera'}},{dataset:{controlPanel:'network'}},{dataset:{controlPanel:'sensor'}}]){
    assert.equal(support.control(button,true).state,'android');assert.equal(support.control(button,false).state,'supported');
  }
  for(const button of [{dataset:{panel:'biometric'}},{dataset:{controlPanel:'location'}},{dataset:{controlPanel:'battery'}},{dataset:{controlPanel:'rotation'}},{id:'quickScreenshot',dataset:{}}])assert.equal(support.control(button,true).state,'supported');
});
test('unavailable Magisk on Google Play is disabled and does not promise ADB root',()=>{
  const result=support.appRoot({enabled:false,available:false},true);
  assert.equal(result.disabled,true);assert.match(result.reason,/Google Play/);assert.match(result.reason,/Gadget/);
  assert.equal(support.appRoot(undefined,true).disabled,true);
});
test('root capability permits disabling active Magisk even if provisioning is unavailable',()=>{
  assert.equal(support.appRoot({enabled:true,available:false},true).disabled,false);
  assert.equal(support.appRoot({enabled:false,available:true},false).disabled,false);
});
test('platform repaint reapplies unavailable Magisk restrictions instead of enabling the button',()=>{
  const root={id:'quickRoot',dataset:{},title:'Root apps',disabled:true};
  const c={devicePlatform:'android',iosInfo:{state:'on'},document:{querySelectorAll:selector=>selector==='.device-controls button'?[root]:[]},
    window:{huntmobToolSupport:support,huntmobTools:{refreshCapabilities(){root.disabled=support.appRoot({enabled:false,available:false},true).disabled;}}}};
  const source=fs.readFileSync('web/ios.js','utf8');vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('function syncIosDeviceControls()'),source.indexOf('function syncPlatformTools()')),c);
  c.syncIosDeviceControls();assert.equal(root.disabled,true);
});
