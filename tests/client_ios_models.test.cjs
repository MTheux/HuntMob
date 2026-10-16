const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{}};vm.runInNewContext(fs.readFileSync('web/ios-models.js','utf8'),context);
const models=context.window.huntmobIosModels;
const seven={name:'iPhone 7',minimum:655360,maximum:1048575};
const eight={name:'iPhone 8',minimum:720896,maximum:1050880};
test('legacy iPhone types do not become compatible just because their name exists',()=>{
  assert.equal(models.compatible(seven,'com.apple.CoreSimulator.SimRuntime.iOS-15-5'),true);
  assert.equal(models.compatible(seven,'com.apple.CoreSimulator.SimRuntime.iOS-16-0'),false);
  assert.equal(models.compatible(eight,'com.apple.CoreSimulator.SimRuntime.iOS-16-4'),true);
  assert.equal(models.compatible(eight,'com.apple.CoreSimulator.SimRuntime.iOS-17-0'),false);
  for(const model of [seven,eight])assert.equal(models.compatible(model,'com.apple.CoreSimulator.SimRuntime.iOS-26-0'),false);
});
test('uninstalled and invalid runtime selections never report compatibility',()=>{
  for(const value of ['','iOS 15.5','missing',null])assert.equal(models.compatible(seven,value),false);
  assert.equal(models.range(seven),'iOS 10–15');
  assert.equal(models.label(seven,26*65536),'iPhone 7 · iOS 10–15');
  assert.equal(models.label(eight,16*65536),'iPhone 8');
});
