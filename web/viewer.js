function currentViewerUrl(){
 const url=new URL('/',location.origin);url.searchParams.set('viewer','1');url.searchParams.set('platform',devicePlatform);
 if(devicePlatform==='ios'&&iosInfo?.lab?.udid)url.searchParams.set('device',iosInfo.lab.udid);
 return url.href;
}
document.querySelector('#openViewer').addEventListener('click',async()=>{
 document.querySelector('#openNativeViewer').href='huntmob-viewer://open?url='+encodeURIComponent(currentViewerUrl());
 document.querySelector('#viewerDialog').showModal();
 const container=document.querySelector('#viewerDownloads');container.replaceChildren();
 try{
  const data=await fetch('/api/viewer/downloads',{cache:'no-store'}).then(r=>r.json());
  for(const artifact of data.artifacts){const row=document.createElement('p'),link=document.createElement('a'),note=document.createElement('small');link.href=artifact.url;link.className='outline';link.textContent=artifact.label;note.textContent=' · '+artifact.validation+' · SHA256 '+artifact.sha256;row.append(link,note);container.append(row);}
  document.querySelector('#viewerStatus').textContent=data.artifacts.length?'Pacotes portáteis; assinatura/notarização de distribuição ainda pendentes.':data.reason || 'Pacotes indisponíveis.';
 }catch{document.querySelector('#viewerStatus').textContent='Não foi possível consultar os pacotes.';}
});
document.querySelector('#openBrowserViewer').addEventListener('click',()=>window.open(currentViewerUrl(),'huntmob-device-viewer','popup,width=560,height=920'));
document.querySelector('#copyIosIdentity').addEventListener('click',async()=>{const value=iosInfo?.identity?.value;if(!value)return;try{await navigator.clipboard.writeText(value);notify('UUID do Simulator copiado.');}catch{notify('Selecione o identificador e copie manualmente.');}});
document.querySelector('#exportIosIdentity').addEventListener('click',()=>{if(!iosInfo?.identity?.available)return;const blob=new Blob([JSON.stringify(iosInfo.identity,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='huntmob-ios-identity.json';link.click();URL.revokeObjectURL(url);});
const viewerParameters=new URLSearchParams(location.search);
if(viewerParameters.get('viewer')==='1'){
 document.body.classList.add('viewer-mode');analysisPreference='false';setAnalysisOpen(false);
 if(viewerParameters.get('platform')==='ios')switchDevicePlatform('ios');
 const expected=viewerParameters.get('device');
 if(expected){
  let blocked=false;
  setInterval(async()=>{
   if(blocked)return;
   try{const info=await fetch('/api/ios/status',{cache:'no-store'}).then(r=>r.json());if(info.lab?.udid!==expected){blocked=true;stopDeviceScreen();const overlay=document.createElement('dialog');overlay.innerHTML='<form method="dialog"><h2>O dispositivo selecionado mudou</h2><p>Reabra a janela a partir do lab desejado.</p></form>';document.body.append(overlay);overlay.addEventListener('cancel',e=>e.preventDefault());overlay.showModal();}}catch{}
  },2000);
 }
}
if(document.body.classList.contains('viewer-mode')){
 const actions=document.createElement('div');actions.className='viewer-actions';
 const keyboard=document.createElement('button');keyboard.textContent='Teclado';keyboard.addEventListener('click',()=>document.querySelector('#openDeviceKeyboard').click());
 const back=document.createElement('button');back.textContent='Voltar / Home';back.addEventListener('click',()=>remoteDeviceInput({action:devicePlatform==='ios'?'home':'back'}).catch(error=>notify(error.message)));
 actions.append(keyboard,back);document.body.append(actions);
}
