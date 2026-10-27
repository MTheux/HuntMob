const {test}=require('node:test');
const assert=require('node:assert/strict');
const {keyboardAction,inputQueue,zoomPan,fitPan}=require('../web/screen-interaction.js');

test('physical typing stays in order while a previous key is in flight',async()=>{
  const sent=[];let release;const blocked=new Promise(resolve=>release=resolve);
  const queue=inputQueue(async input=>{sent.push(input.text);if(sent.length===1)await blocked;},()=>true,assert.fail);
  const first=queue.push({text:'a'},'lab');
  queue.push({text:'b'},'lab');const last=queue.push({text:'c'},'lab');
  await Promise.resolve();assert.deepEqual(sent,['a']);release();await first;await last;
  assert.deepEqual(sent,['a','b','c']);
});
test('queued keys from a replaced device or stream cannot reach the new one',async()=>{
  const sent=[];let current='old',release;const blocked=new Promise(resolve=>release=resolve);
  const queue=inputQueue(async input=>{sent.push(input.text);if(sent.length===1)await blocked;},scope=>scope===current,assert.fail);
  queue.push({text:'a'},'old');queue.push({text:'b'},'old');
  await Promise.resolve();current='new';const last=queue.push({text:'c'},'new');release();await last;
  assert.deepEqual(sent,['a','c']);
});
test('one rejected input does not break subsequent physical keys',async()=>{
  const errors=[],sent=[];
  const queue=inputQueue(async input=>{if(input.text==='a')throw new Error('disconnected');sent.push(input.text);},()=>true,error=>errors.push(error.message));
  queue.push({text:'a'},'lab');await queue.push({text:'b'},'lab');
  assert.deepEqual(sent,['b']);assert.deepEqual(errors,['disconnected']);
});
test('browser shortcuts and composition are not sent as native text',()=>{
  for(const event of [{key:'f',ctrlKey:true},{key:'a',metaKey:true},{key:'x',altKey:true},{key:'a',isComposing:true},{key:'Shift'}])assert.equal(keyboardAction(event),undefined);
  assert.deepEqual(keyboardAction({key:'Enter'}),{action:'key',key:'Enter'});
  assert.deepEqual(keyboardAction({key:'Escape'},{platform:'ios'}),{action:'home'});
  assert.deepEqual(keyboardAction({key:'Escape'}),{action:'back'});
  assert.deepEqual(keyboardAction({key:'!'}),{action:'text',text:'!'});
  assert.deepEqual(keyboardAction({key:'ç'}),{action:'text',text:'ç'});
  assert.equal(keyboardAction({key:'ç'},{mode:'ascii'}),undefined);
  assert.equal(keyboardAction({key:'!'},{mode:'adb'}),undefined);
});
test('wheel zoom keeps the same point under the cursor after panning and scrolling',()=>{
  const point={x:130,y:250},pan={x:-200,y:45},scroll={x:400,y:120},after={x:180,y:0};
  for(const next of [.5,.75,1,1.5,2.5]){
    const moved=zoomPan(point,pan,scroll,1.2,next,after);
    for(const axis of ['x','y'])assert.ok(Math.abs((point[axis]+scroll[axis]-pan[axis])/1.2-(point[axis]+after[axis]-moved[axis])/next)<1e-8);
  }
});
test('fit centers the complete tile, including its header, even after a distant drag',()=>{
  const bounds={left:12000,top:8000,right:12300,bottom:8640},width=1000,height=600,zoom=.85;
  const pan=fitPan(bounds,width,height,zoom);
  const left=bounds.left*zoom+pan.x,right=bounds.right*zoom+pan.x;
  const top=bounds.top*zoom+pan.y,bottom=bounds.bottom*zoom+pan.y;
  assert.ok(left>=0&&right<=width&&top>=0&&bottom<=height);
  assert.ok(Math.abs((left+right)/2-width/2)<1e-8);
  assert.ok(Math.abs((top+bottom)/2-height/2)<1e-8);
});
