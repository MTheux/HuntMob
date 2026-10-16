const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/video.js','utf8');
function context(){
 const timers=new Map();let next=0,calls=0;
 const c={devicePlatform:'android',runtimeDevice:{state:'on'},screenGeneration:7,document:{querySelector:()=>({hidden:false})},window:{VideoDecoder:function(){},setTimeout(fn,delay){timers.set(++next,{fn,delay});return next;},clearTimeout(id){timers.delete(id);}}};
 vm.createContext(c);vm.runInContext(source,c);c.startDirectVideo=()=>calls++;
 return {c,timers,calls:()=>calls};
}
test('H264 recovery is delayed and bounded after consecutive failures',()=>{
 const {c,timers,calls}=context();
 for(const delay of [5000,10000,20000]){c.scheduleDirectVideoRetry(7);assert.equal(timers.size,1);const timer=[...timers.values()][0];assert.equal(timer.delay,delay);timer.fn();}
 c.scheduleDirectVideoRetry(7);assert.equal(timers.size,0);assert.equal(calls(),3);
});
test('recovery never starts on a replaced lab, iOS, or offline device',()=>{
 for(const update of [{screenGeneration:8},{devicePlatform:'ios'},{runtimeDevice:{state:'off'}}]){
  const {c,timers,calls}=context();c.scheduleDirectVideoRetry(7);Object.assign(c,update);[...timers.values()][0].fn();assert.equal(calls(),0);
 }
});
test('screen teardown cancels pending recovery',()=>{
 const {c,timers}=context();c.scheduleDirectVideoRetry(7);c.stopDirectVideo();assert.equal(timers.size,0);
});
