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
function rendererContext(){
 const {c}=context(),callbacks=new Map(),painted=[],closed=[],signal={aborted:false};let next=0,frames=0,geometry=0;
 c.window.requestAnimationFrame=fn=>{callbacks.set(++next,fn);return next;};
 c.window.cancelAnimationFrame=id=>callbacks.delete(id);
 c.fitPhoneFrame=()=>geometry++;
 const canvas={width:0,height:0,dataset:{},getContext:()=>({drawImage:frame=>painted.push(frame.id)})};
 const renderer=c.androidFrameRenderer(canvas,{signal,onFrame:()=>frames++});
 return {renderer,canvas,callbacks,painted,closed,signal,frames:()=>frames,geometry:()=>geometry,
  frame:id=>({id,displayWidth:576,displayHeight:1280,close:()=>closed.push(id)}),
  paint(){const entries=[...callbacks];callbacks.clear();entries.forEach(([,fn])=>fn());}};
}
test('decoded frame bursts paint the latest frame once and release every buffer',()=>{
 const r=rendererContext();[1,2,3].forEach(id=>r.renderer.push(r.frame(id)));
 assert.equal(r.callbacks.size,1);assert.deepEqual(r.closed,[1,2]);r.paint();
 assert.deepEqual(r.painted,[3]);assert.deepEqual(r.closed,[1,2,3]);assert.equal(r.frames(),1);
 assert.equal(r.canvas.dataset.droppedRenderFrames,'2');
 r.renderer.push(r.frame(4));r.paint();assert.equal(r.geometry(),1);
});
test('stream teardown and abort release frames without painting a replaced screen',()=>{
 const r=rendererContext();r.renderer.push(r.frame(1));r.renderer.clear();
 assert.equal(r.callbacks.size,0);assert.deepEqual(r.closed,[1]);
 r.renderer.push(r.frame(2));r.signal.aborted=true;r.paint();r.renderer.push(r.frame(3));
 assert.deepEqual(r.closed,[1,2,3]);assert.deepEqual(r.painted,[]);assert.equal(r.callbacks.size,0);
});
