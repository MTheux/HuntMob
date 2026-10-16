// Read-only checks run on the current client, never on an arbitrary destination.
async function collectClientValidation(fetcher, environment) {
  const samples=[],errors=[];
  for(let i=0;i<3;i++){
    const started=environment.now();
    try{
      const response=await fetcher('/api/client/ping',{cache:'no-store',signal:AbortSignal.timeout(8000)});
      if(!response.ok){errors.push('HTTP_'+response.status);continue;}
      const result=await response.json();
      if(result.ok!==true || result.version!==1){errors.push('invalid_ping');continue;}
      samples.push(Math.max(0,Math.round(environment.now()-started)));
    }catch{errors.push('unreachable');}
  }
  const sorted=[...samples].sort((a,b)=>a-b);
  return {version:1,collected_at:new Date().toISOString(),client:environment.client,connection:{state:samples.length===3?'connected':samples.length?'partial':'unreachable',samples_ms:samples,median_ms:sorted.length?sorted[Math.floor(sorted.length/2)]:null,errors},display:environment.display(),manual_checks:{touch:'not_tested',drag:'not_tested',keyboard:'not_tested',reconnect:'not_tested'},full_journey_validated:false};
}
function clientPlatform(){
  const agent=navigator.userAgent;
  if(/iPad/.test(agent)||(/Macintosh/.test(agent)&&navigator.maxTouchPoints>1))return 'iPadOS';
  if(/iPhone/.test(agent))return 'iOS';
  if(/Windows/.test(agent))return 'Windows';
  if(/Android/.test(agent))return 'Android';
  if(/Macintosh/.test(agent))return 'macOS';
  return /Linux/.test(agent)?'Linux':'unknown';
}
let latestClientValidation;
document.querySelector('#checkClientConnection').addEventListener('click',async event=>{
  const button=event.currentTarget,status=document.querySelector('#clientCheckStatus');button.disabled=true;status.textContent='Verificando este aparelho…';
  document.querySelector('#exportClientCheck').disabled=true;
  try{
    latestClientValidation=await collectClientValidation(fetch,{now:()=>performance.now(),client:{platform:clientPlatform(),secure_context:window.isSecureContext,webcodecs:typeof VideoDecoder!=='undefined',pointer_events:typeof PointerEvent!=='undefined',transport:location.protocol==='https:'?'https':'http'},display:()=>{
      const canvas=document.querySelector('#deviceVideo'),image=document.querySelector('#deviceScreen');
      const direct=!canvas.hidden&&Number(canvas.dataset.renderedFrames)>0;
      return {platform:devicePlatform,visible:direct || (!image.hidden && image.naturalWidth>0),transport:direct?'h264-webcodecs':!image.hidden&&image.naturalWidth>0?'mjpeg':'disconnected',decoded_frames:direct?Number(canvas.dataset.renderedFrames):null,last_decoded_frame_age_ms:direct?Math.max(0,Date.now()-Number(canvas.dataset.lastFrameAt)):null};
    }});
    const r=latestClientValidation;
    status.textContent=`${r.client.platform} · ${r.connection.samples_ms.length}/3 respostas${r.connection.median_ms!==null?' · mediana '+r.connection.median_ms+' ms':''} · imagem ${r.display.visible?'visível':'não exibida'}. Toque, arraste e teclado ainda exigem teste manual.`;
    document.querySelector('#exportClientCheck').disabled=false;
  }catch{status.textContent='Não foi possível concluir o teste neste navegador.';}
  finally{button.disabled=false;}
});
document.querySelector('#exportClientCheck').addEventListener('click',()=>{
  if(!latestClientValidation)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(latestClientValidation,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='huntmob-client-check.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
