const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ios=fs.readFileSync('web/ios.js','utf8');
const start=ios.slice(ios.indexOf('function startIosScreen('),ios.indexOf('async function iosAction('));
function setup(){
 const screen={hidden:true,naturalWidth:603,naturalHeight:1311,dataset:{}},status={},timers=[];
 let calls=0;const c={fitPhoneFrame:()=>{},screenGeneration:4,devicePlatform:'ios',runtimeDevice:{state:'on'},screenRetries:0,
 document:{querySelector:selector=>selector==='#deviceScreen'?screen:selector==='#screenConnection'?status:{}},
 window:{huntmobOperator:{mediaUrl:()=>Promise.resolve('/api/ios/stream?_operator_ticket=fixture')},setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;}},startDeviceScreen:()=>calls++};
 vm.createContext(c);vm.runInContext(start,c);return {c,screen,status,timers,calls:()=>calls};
}
test('iOS video retries failed startup with bounded backoff',()=>{
 const {c,screen,timers,calls}=setup();c.startIosScreen(4);
 for(const delay of [500,1000,2000,4000,5000]){screen.onerror();assert.equal(timers.at(-1).delay,delay);timers.at(-1).fn();}
 screen.onerror();assert.equal(timers.length,5);assert.equal(calls(),5);
});
test('stale, offline and replaced-platform video callbacks never reconnect',()=>{
 for(const update of [{screenGeneration:5},{devicePlatform:'android'},{runtimeDevice:{state:'off'}}]){
  const {c,screen,timers,calls}=setup();c.startIosScreen(4);screen.onerror();Object.assign(c,update);timers[0].fn();screen.onerror();
  assert.equal(calls(),0);assert.equal(timers.length,1);
 }
});
test('a received frame clears retry history and records actual geometry',()=>{
 const {c,screen}=setup();c.screenRetries=5;c.startIosScreen(4);screen.onload();
 assert.equal(c.screenRetries,0);assert.equal(screen.hidden,false);assert.equal(screen.dataset.frameWidth,603);
});
