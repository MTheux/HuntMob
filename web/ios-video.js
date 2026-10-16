// Keep one JPEG decoding and one newest pending frame, never a playback queue.
let iosCanvasAbort;

class IosMjpegParser {
  constructor(){this.buffer=new Uint8Array();this.frames=0;}
  push(chunk){
    if(this.buffer.length+chunk.length>8*1024*1024)throw new Error('Fila de vídeo iOS excedeu o limite.');
    const joined=new Uint8Array(this.buffer.length+chunk.length);
    joined.set(this.buffer);joined.set(chunk,this.buffer.length);this.buffer=joined;
    let newest;
    while(this.buffer.length){
      let end=-1;
      for(let i=0;i+3<this.buffer.length;i++){
        if(this.buffer[i]===13&&this.buffer[i+1]===10&&this.buffer[i+2]===13&&this.buffer[i+3]===10){end=i;break;}
      }
      if(end<0){if(this.buffer.length>4096)throw new Error('Cabeçalho de vídeo iOS inválido.');break;}
      if(end>4096)throw new Error('Cabeçalho de vídeo iOS inválido.');
      const header=new TextDecoder().decode(this.buffer.subarray(0,end));
      const length=header.match(/(?:^|\r\n)Content-Length:\s*(\d+)\s*(?:\r\n|$)/i);
      const size=length?Number(length[1]):0;
      if(!/Content-Type:\s*image\/jpeg(?:\r\n|$)/i.test(header)||size<4||size>4*1024*1024)throw new Error('Frame de vídeo iOS inválido.');
      const start=end+4;
      if(this.buffer.length<start+size+2)break;
      if(this.buffer[start]!==255||this.buffer[start+1]!==216||this.buffer[start+size-2]!==255||this.buffer[start+size-1]!==217||this.buffer[start+size]!==13||this.buffer[start+size+1]!==10)throw new Error('Frame JPEG iOS inválido.');
      newest=this.buffer.slice(start,start+size);this.frames++;
      this.buffer=this.buffer.slice(start+size+2);
    }
    return newest;
  }
}

class IosLatestFrame {
  constructor(decode,draw,onError){
    this.decode=decode;this.draw=draw;this.onError=onError;
    this.pending=undefined;this.busy=false;this.closed=false;this.dropped=0;
  }
  offer(bytes){
    if(this.closed)return;
    if(this.pending)this.dropped++;
    this.pending=bytes;
    if(!this.busy)void this.drain();
  }
  async drain(){
    this.busy=true;
    try{
      while(this.pending&&!this.closed){
        const bytes=this.pending;this.pending=undefined;
        const bitmap=await this.decode(bytes);
        try{if(!this.closed)this.draw(bitmap);}finally{bitmap.close();}
      }
    }catch(error){this.close();this.onError(error);}
    finally{this.busy=false;}
  }
  close(){this.closed=true;this.pending=undefined;}
}

function stopIosCanvas(){iosCanvasAbort?.abort();iosCanvasAbort=undefined;}

async function decodeIosDeviceCanvas(canvas,route,{signal,onFrame}){
  const context=canvas.getContext('2d',{alpha:false,desynchronized:true}),parser=new IosMjpegParser();
  let reader,decodeError;
  const latest=new IosLatestFrame(bytes=>createImageBitmap(new Blob([bytes],{type:'image/jpeg'})),bitmap=>{
    if(signal.aborted)return;
    if(canvas.width!==bitmap.width||canvas.height!==bitmap.height){canvas.width=bitmap.width;canvas.height=bitmap.height;}
    context.drawImage(bitmap,0,0);canvas.dataset.frameWidth=bitmap.width;canvas.dataset.frameHeight=bitmap.height;
    canvas.dataset.renderedFrames=String(Number(canvas.dataset.renderedFrames||0)+1);canvas.dataset.lastFrameAt=String(Date.now());
    fitPhoneFrame(canvas,bitmap.width,bitmap.height,'ios');canvas.hidden=false;onFrame();
  },error=>{decodeError=error;reader?.cancel().catch(()=>{});});
  try{
    const response=await fetch(route,{signal,cache:'no-store'});if(!response.ok||!response.body)throw new Error('Vídeo iOS indisponível.');
    reader=response.body.getReader();
    while(!signal.aborted){const {value,done}=await reader.read();if(done)break;const frame=parser.push(value);if(frame)latest.offer(frame);}
    if(decodeError)throw decodeError;
  }finally{latest.close();await reader?.cancel().catch(()=>{});}
}

async function startIosCanvas(generation,onConnected,onFailure){
  stopIosCanvas();
  const abort=new AbortController();iosCanvasAbort=abort;
  const canvas=document.querySelector('#deviceVideo'),image=document.querySelector('#deviceScreen');
  const context=canvas.getContext('2d',{alpha:false,desynchronized:true});
  const current=()=>!abort.signal.aborted&&generation===screenGeneration&&devicePlatform==='ios';
  let frames=0,first=true,last=performance.now(),failed=false;
  canvas.dataset.renderedFrames='0';canvas.dataset.receivedFrames='0';canvas.dataset.droppedFrames='0';
  const fail=()=>{if(current()&&!failed){failed=true;canvas.hidden=true;onFailure();abort.abort();}};
  const latest=new IosLatestFrame(
    bytes=>createImageBitmap(new Blob([bytes],{type:'image/jpeg'})),
    bitmap=>{
      if(!current())return;
      if(canvas.width!==bitmap.width||canvas.height!==bitmap.height){canvas.width=bitmap.width;canvas.height=bitmap.height;}
      context.drawImage(bitmap,0,0);
      canvas.dataset.frameWidth=bitmap.width;canvas.dataset.frameHeight=bitmap.height;
      fitPhoneFrame(canvas,bitmap.width,bitmap.height,'ios');
      canvas.dataset.renderedFrames=String(Number(canvas.dataset.renderedFrames)+1);
      canvas.dataset.lastFrameAt=String(Date.now());canvas.hidden=false;image.hidden=true;
      if(first){first=false;onConnected(bitmap.width,bitmap.height);}
      frames++;
      const now=performance.now();
      if(now-last>=1000){document.querySelector('#screenConnection').textContent=`iOS · ${Math.round(frames*1000/(now-last))} fps · toque contínuo`;frames=0;last=now;}
    },fail);
  const parser=new IosMjpegParser();
  let reader;
  try{
    const response=await fetch('/api/ios/stream?t='+Date.now(),{signal:abort.signal,cache:'no-store'});
    if(!response.ok||!response.body)throw new Error('Vídeo iOS indisponível.');
    reader=response.body.getReader();
    while(current()){
      const {value,done}=await reader.read();
      if(done)break;
      const newest=parser.push(value);
      canvas.dataset.receivedFrames=String(parser.frames);
      if(newest)latest.offer(newest);
      canvas.dataset.droppedFrames=String(latest.dropped);
    }
    if(current())fail();
  }catch(error){if(current())fail();}
  finally{latest.close();if(reader)await reader.cancel().catch(()=>{});}
}
