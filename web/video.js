// Pinned scrcpy H.264 framing, decoded once in the browser. No JPEG transcode.
let videoAbort, videoDecoder;
let videoRetryTimer, directVideoFailures = 0;
let directVideoActive = false;
function scheduleDirectVideoRetry(generation) {
  window.clearTimeout(videoRetryTimer);
  if (!window.VideoDecoder || devicePlatform !== 'android' || runtimeDevice?.state !== 'on' || generation !== screenGeneration || ++directVideoFailures > 3) return;
  videoRetryTimer = window.setTimeout(() => {
    if (generation === screenGeneration && devicePlatform === 'android' && runtimeDevice?.state === 'on') startDirectVideo(generation);
  }, Math.min(20000, 5000 * 2 ** (directVideoFailures - 1)));
}
function stopDirectVideo() {
  window.clearTimeout(videoRetryTimer);
  directVideoActive = false;
  videoAbort?.abort(); videoAbort = undefined;
  if (videoDecoder && videoDecoder.state !== 'closed') videoDecoder.close();
  videoDecoder = undefined;
  document.querySelector('#deviceVideo').hidden = true;
}
function androidFrameRenderer(canvas, {signal, onFrame}) {
  const context=canvas.getContext('2d',{alpha:false,desynchronized:true});
  let pending, animation, width, height;
  function clear() {
    if(animation!==undefined)window.cancelAnimationFrame(animation);
    animation=undefined;pending?.close();pending=undefined;
  }
  function paint() {
    animation=undefined;const frame=pending;pending=undefined;
    if(!frame)return;
    try {
      if(signal.aborted)return;
      const changed=canvas.width!==frame.displayWidth||canvas.height!==frame.displayHeight;
      if(changed){canvas.width=frame.displayWidth;canvas.height=frame.displayHeight;}
      if(width!==frame.displayWidth||height!==frame.displayHeight){
        width=frame.displayWidth;height=frame.displayHeight;
        canvas.dataset.frameWidth=frame.displayWidth;canvas.dataset.frameHeight=frame.displayHeight;
        fitPhoneFrame(canvas,frame.displayWidth,frame.displayHeight,'android');
      }
      context.drawImage(frame,0,0,canvas.width,canvas.height);canvas.hidden=false;
      canvas.dataset.renderedFrames=String(Number(canvas.dataset.renderedFrames||0)+1);
      canvas.dataset.lastFrameAt=String(Date.now());onFrame();
    } finally {frame.close();}
  }
  return {push(frame) {
    if(signal.aborted){frame.close();return;}
    // Keep only the newest decoded frame until the display can paint it.
    // Bursts and background tabs cannot accumulate GPU-backed VideoFrames.
    if(pending){pending.close();canvas.dataset.droppedRenderFrames=String(Number(canvas.dataset.droppedRenderFrames||0)+1);}
    pending=frame;
    if(animation===undefined)animation=window.requestAnimationFrame(paint);
  },clear};
}
async function decodeAndroidVideo(canvas, route, {signal, onFrame}) {
  const abort={signal};
  let videoDecoder, reader, config, decodeError, awaitingKey=true;
  const renderer=androidFrameRenderer(canvas,{signal,onFrame});
  try {
    const response = await fetch(route,{signal:abort.signal,cache:'no-store'});
    if (!response.ok || !response.body) throw new Error('Vídeo H.264 indisponível');
    reader = response.body.getReader(); let buffer = new Uint8Array(), hasCodec = false;
    const configure = data => {
      let sps;
      for (let i=0;i<data.length-5;i++) {
        let pos = -1;
        if (data[i]===0 && data[i+1]===0 && data[i+2]===1) pos=i+3;
        else if (data[i]===0 && data[i+1]===0 && data[i+2]===0 && data[i+3]===1) pos=i+4;
        if (pos>=0 && (data[pos]&31)===7) { sps=data.slice(pos); break; }
      }
      if (!sps || sps.length<4) throw new Error('Configuração H.264 inválida');
      const codec='avc1.'+[sps[1],sps[2],sps[3]].map(x=>x.toString(16).padStart(2,'0')).join('');
      if (videoDecoder && videoDecoder.state!=='closed') videoDecoder.close();
      renderer.clear();
      videoDecoder = new VideoDecoder({
        output:renderer.push,
        error:() => { decodeError=new Error('Decodificação de vídeo interrompida'); reader?.cancel().catch(()=>{}); }
      });
      videoDecoder.configure({codec,optimizeForLatency:true,hardwareAcceleration:'prefer-hardware'});
      config=data;awaitingKey=true;
    };
    while (!abort.signal.aborted) {
      const {value,done}=await reader.read(); if(done) break;
      const next=new Uint8Array(buffer.length+value.length);next.set(buffer);next.set(value,buffer.length);buffer=next;
      if(buffer.length>8*1024*1024) throw new Error('Fila de vídeo excedeu limite');
      if(!hasCodec) {if(buffer.length<4) continue;if(new TextDecoder().decode(buffer.slice(0,4))!=='h264') throw new Error('Codec inválido');buffer=buffer.slice(4);hasCodec=true;}
      let offset=0;
      while(buffer.length-offset>=12) {
        const header=new DataView(buffer.buffer,buffer.byteOffset+offset,12);
        const flags=header.getBigUint64(0), size=header.getUint32(8);
        if(flags & (1n<<63n)) {awaitingKey=true;offset+=12;continue;}
        if(size===0) {offset+=12;continue;}
        if(size>4*1024*1024) throw new Error('Pacote de vídeo inválido');
        if(buffer.length-offset<12+size) break;
        let data=buffer.slice(offset+12,offset+12+size);offset+=12+size;
        if(flags & (1n<<62n)) {configure(data);continue;}
        const key=Boolean(flags & (1n<<61n));
        if(!videoDecoder || (awaitingKey&&!key)) continue;
        // A lagging decoder skips deltas and resumes at the next keyframe.
        if(videoDecoder.decodeQueueSize>6) {awaitingKey=true;continue;}
        if(key && config) {const full=new Uint8Array(config.length+data.length);full.set(config);full.set(data,config.length);data=full;}
        awaitingKey=false;
        videoDecoder.decode(new EncodedVideoChunk({type:key?'key':'delta',timestamp:Number(flags & ((1n<<61n)-1n)),data}));
      }
      buffer=buffer.slice(offset);
    }
    if(decodeError)throw decodeError;
  } finally {
    renderer.clear();
    if(videoDecoder && videoDecoder.state!=='closed')videoDecoder.close();
    await reader?.cancel().catch(()=>{});
  }
}
async function startDirectVideo(generation) {
  if(!window.VideoDecoder)return false;
  videoAbort=new AbortController();const abort=videoAbort;
  const canvas=document.querySelector('#deviceVideo');canvas.dataset.renderedFrames='0';
  let receivedFrame=false,frames=0,interval=performance.now(),lastFrame;
  try {
    await decodeAndroidVideo(canvas,'/api/device/video',{signal:abort.signal,onFrame:()=>{
      if(generation!==screenGeneration||abort.signal.aborted)return;
      const compatible=document.querySelector('#deviceScreen');
      compatible.hidden=true;directVideoActive=true;
      if(!receivedFrame){receivedFrame=true;directVideoFailures=0;compatible.onload=compatible.onerror=null;compatible.removeAttribute('src');document.querySelector('#screenConnection').textContent='H.264 direto · toque contínuo';}
      const now=performance.now();
      // A static Android display emits no frames. Its idle time must not turn
      // the next animation's readout into a misleading 0 fps measurement.
      if(lastFrame===undefined||now-lastFrame>500){frames=0;interval=now;document.querySelector('#screenConnection').textContent='H.264 direto · toque contínuo';}
      else frames++;
      lastFrame=now;
      if(now-interval>=500){document.querySelector('#screenConnection').textContent=`H.264 · ${Math.round(frames*1000/(now-interval))} fps · toque contínuo`;frames=0;interval=now;}
    }});
  } catch(error){if(!abort.signal.aborted)console.info('Vídeo compatível:',error.message);}
  finally {
    if(generation===screenGeneration && runtimeDevice?.state==='on'){
      stopDirectVideo();startCompatibleScreen(generation);scheduleDirectVideoRetry(generation);
    }
  }
  return true;
}
