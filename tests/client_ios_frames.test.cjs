const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/ios-video.js','utf8');
const ctx={Uint8Array,TextDecoder};vm.createContext(ctx);vm.runInContext(source,ctx);
const Parser=vm.runInContext('IosMjpegParser',ctx),Latest=vm.runInContext('IosLatestFrame',ctx);
const jpeg=n=>Buffer.from([255,216,n,255,217]);
const packet=n=>Buffer.concat([Buffer.from('--huntmob\r\nContent-Type: image/jpeg\r\nContent-Length: 5\r\n\r\n'),jpeg(n),Buffer.from('\r\n')]);
test('multipart survives arbitrary boundaries and keeps only the newest completed frame',()=>{
 const p=new Parser();let last;
 const data=Buffer.concat([packet(1),packet(2)]);
 for(const byte of data){const result=p.push(Uint8Array.of(byte));if(result)last=result;}
 assert.deepEqual(Buffer.from(last),jpeg(2));assert.equal(p.frames,2);
 assert.deepEqual(Buffer.from(p.push(Buffer.concat([packet(3),packet(4),packet(5)]))),jpeg(5));
 assert.equal(p.frames,5);assert.equal(p.buffer.length,0);
});
test('malformed or oversized frames never reach the decoder',()=>{
 for(const data of [Buffer.from('--x\r\nContent-Type: text/html\r\nContent-Length: 5\r\n\r\n'),
 Buffer.from('--x\r\nContent-Type: image/jpeg\r\nContent-Length: 5000000\r\n\r\n'),
 Buffer.alloc(4097,65),Buffer.from(packet(1).toString('binary').replace('Content-Length: 5','Content-Length: 4'),'binary')]){
  assert.throws(()=>new Parser().push(data));
 }
});
test('slow decoding holds at most one pending frame and closes every bitmap',async()=>{
 let release,finished;const blocked=new Promise(resolve=>release=resolve),done=new Promise(resolve=>finished=resolve);
 const decoded=[],drawn=[],closed=[];
 const latest=new Latest(async n=>{decoded.push(n);if(n===1)await blocked;return {n,close:()=>closed.push(n)};},
 bitmap=>{drawn.push(bitmap.n);if(bitmap.n===3)finished();},assert.fail);
 latest.offer(1);latest.offer(2);latest.offer(3);release();await done;await Promise.resolve();
 assert.deepEqual(decoded,[1,3]);assert.deepEqual(drawn,[1,3]);assert.deepEqual(closed,[1,3]);assert.equal(latest.dropped,1);
 latest.close();latest.offer(4);assert.deepEqual(decoded,[1,3]);
});
test('disconnect during decoding closes the late bitmap without drawing it',async()=>{
 let release,decoded;const blocked=new Promise(resolve=>release=resolve),done=new Promise(resolve=>decoded=resolve);
 let draws=0,closed=0;const latest=new Latest(async()=>{await blocked;return {close:()=>{closed++;decoded();}};},()=>draws++,assert.fail);
 latest.offer(1);latest.close();release();await done;
 assert.equal(draws,0);assert.equal(closed,1);
});
