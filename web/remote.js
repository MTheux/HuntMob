// Touch keyboard and tablet presentation share the existing device/API scope.
const keyboardDialog=document.querySelector('#remoteKeyboardDialog');
document.querySelector('#openDeviceKeyboard').addEventListener('click',()=>keyboardDialog.showModal());
async function remoteDeviceInput(payload){
  const endpoint=devicePlatform==='ios'?'/api/ios/action':directVideoActive?'/api/device/direct-input':'/api/device/input';
  return authorizedPost(endpoint,payload);
}
document.querySelector('#sendDeviceText').addEventListener('click',async()=>{
  const input=document.querySelector('#remoteKeyboardText'),status=document.querySelector('#remoteKeyboardStatus'),button=document.querySelector('#sendDeviceText');
  const text=input.value;
  if(!text || text.length>256){status.textContent='Digite até 256 caracteres.';return;}
  if((devicePlatform==='ios' && !/^[\x20-\x7e]+$/.test(text)) || (devicePlatform!=='ios' && !directVideoActive && !/^[A-Za-z0-9 @._+:/-]+$/.test(text))){status.textContent='Este canal aceita apenas texto ASCII. Use o teclado do app para outros caracteres.';return;}
  button.disabled=true;
  try{await remoteDeviceInput({action:'text',text});input.value='';status.textContent='Texto enviado ao dispositivo.';}
  catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
});
document.querySelectorAll('[data-remote-key]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;
  try{await remoteDeviceInput({action:'key',key:button.dataset.remoteKey});document.querySelector('#remoteKeyboardStatus').textContent='Tecla enviada.';}
  catch(error){document.querySelector('#remoteKeyboardStatus').textContent=error.message;}
  finally{button.disabled=false;}
}));
if(matchMedia('(max-width:1100px)').matches && analysisPreference===null){analysisPreference='false';setAnalysisOpen(false);}
fetch('/api/remote/status',{cache:'no-store'}).then(r=>r.json()).then(data=>{
  if(data.active){const badge=document.createElement('span');badge.className='safe-badge';badge.textContent='Tailscale · privado';badge.title='Acesso restrito à identidade do proprietário';document.querySelector('.top-actions').prepend(badge);}
}).catch(()=>{});

const deviceListToggle=document.querySelector('#toggleDeviceList');
deviceListToggle.addEventListener('click',()=>{
 const open=!document.body.classList.contains('show-device-list');document.body.classList.toggle('show-device-list',open);deviceListToggle.setAttribute('aria-expanded',String(open));
});
document.querySelector('.device-list').addEventListener('click',event=>{
 if(event.target.closest('button') && !event.target.closest('.aside-head')){document.body.classList.remove('show-device-list');deviceListToggle.setAttribute('aria-expanded','false');}
});
