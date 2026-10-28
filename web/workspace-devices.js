// Each tile owns its decoder, gesture queue and stable backend identity.
const companionTiles=new Map();
window.huntmobAdditionalOnline=()=>Array.from(companionTiles.values()).filter(tile=>tile.online()).length;
let workspaceDeviceBusy=false,workspaceListBusy=false,workspaceShown='',workspaceAgentConfig;
function workspaceParams(workspace,device){return new URLSearchParams({workspace,device}).toString();}
function clearCompanionTiles(){for(const item of companionTiles.values())item.dispose();companionTiles.clear();phoneCanvas.classList.remove('has-companions');}
function syncWorkspaceButtons(){
  const available=devicePlatform==='android'&&!!activeLab.id;
  document.querySelector('#addWorkspaceDevice').disabled=!available||workspaceDeviceBusy||companionTiles.size>=3;
  document.querySelector('#connectWorkspaceAgent').disabled=!available;
  document.querySelector('#createRootCompanion').disabled=!available||runtimeDevice?.state!=='on'||workspaceDeviceBusy;
  document.querySelector('#primaryDeviceSerial').textContent=available?document.querySelector('#stageSerial').textContent:'';
  if(devicePlatform==='android')document.querySelector('#runtimeCount').textContent=String((runtimeDevice?.state==='on'?1:0)+window.huntmobAdditionalOnline());
  window.huntmobSidebar?.sync();
}
function companionTile(device,workspace){
  const tile=document.createElement('section');tile.className='device-tile';tile.dataset.deviceId=device.id;
  const header=document.createElement('header');header.className='device-tile-head';
  const ios=device.platform==='ios';
  const name=document.createElement('strong');name.textContent=ios?'iPhone · '+device.runtime.replace('com.apple.CoreSimulator.SimRuntime.','').replaceAll('-','.').replace('iOS.','iOS '):'Android · API '+device.android_api+' · '+(device.root_mode==='stock'?'sem root':'com root');
  const serial=document.createElement('small');serial.textContent=device.serial;serial.title=device.serial;
  const status=document.createElement('span');status.className='companion-state';status.setAttribute('role','status');
  header.append(name,serial,status);
  const phone=document.createElement('div');phone.className='phone';phone.dataset.platform=ios?'ios':'android';
  const canvas=document.createElement('canvas');canvas.className='device-screen';canvas.tabIndex=0;canvas.hidden=true;canvas.setAttribute('aria-label','Tela interativa '+device.serial);canvas.style.touchAction='none';
  const placeholder=document.createElement('div');placeholder.className='companion-placeholder';placeholder.textContent='Conectando aparelho…';phone.append(canvas,placeholder);
  const controls=document.createElement('div');controls.className='companion-controls';
  let abort,retry,disposed=false,connected=false,pointer,queue=[],sending=false,lastPoint={x:0,y:0};
  const identity={workspace_id:workspace,device_id:device.id};
  const post=(action,extra={})=>authorizedPost('/api/workspace/device/action',{...identity,action,...extra,...(action==='input'?{session_generation:device.session_generation}:{})});
  async function sendTouch(event){
    if(event.phase==='move'&&queue.at(-1)?.phase==='move')queue[queue.length-1]=event;else queue.push(event);
    if(queue.length>64){queue=[];cancel();status.textContent='Fila de entrada excedeu o limite; gesto cancelado.';return;}
    if(sending)return;sending=true;
    try{while(queue.length)await post('input',{input:{action:'touch',...queue.shift()}});}
    catch(error){queue=[];status.textContent=error.message;}
    finally{sending=false;}
  }
  const point=event=>{const r=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))};};
  function cancel(){if(pointer!==undefined){sendTouch({phase:'cancel',...lastPoint});pointer=undefined;}}
  canvas.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();if(!connected||pointer!==undefined)return;canvas.focus({preventScroll:true});pointer=event.pointerId;canvas.setPointerCapture(pointer);lastPoint=point(event);sendTouch({phase:'down',...lastPoint});});
  canvas.addEventListener('pointermove',event=>{if(event.pointerId===pointer){lastPoint=point(event);sendTouch({phase:'move',...lastPoint});}});
  canvas.addEventListener('pointerup',event=>{if(event.pointerId===pointer){lastPoint=point(event);pointer=undefined;sendTouch({phase:'up',...lastPoint});}});
  canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('lostpointercapture',cancel);window.addEventListener('blur',cancel);
  const keyboard=window.huntmobInteraction.inputQueue(input=>post('input',{input}),generation=>!disposed&&connected&&device.session_generation===generation,error=>{status.textContent=error.message;});
  canvas.addEventListener('keydown',event=>{
    const input=window.huntmobInteraction.keyboardAction(event,{platform:ios?'ios':'android',mode:ios?'ascii':'unicode'});
    if(!input||!connected)return;event.preventDefault();void keyboard.push(input,device.session_generation);
  });
  async function video(){
    if(disposed||abort)return;abort=new AbortController();const session=abort;
    try{
      if(!ios&&!window.VideoDecoder)throw new Error('Este navegador precisa de WebCodecs para vários Androids.');
      const decode=ios?decodeIosDeviceCanvas:decodeAndroidVideo;
      await decode(canvas,'/api/workspace/device/video?'+workspaceParams(workspace,device.id),{signal:session.signal,onFrame:()=>{connected=true;placeholder.hidden=true;status.textContent='ONLINE';status.dataset.online='true';}});
    }catch(error){if(!session.signal.aborted){status.textContent=error.message;}}
    finally{if(abort===session)abort=undefined;connected=false;if(!disposed&&device.online)retry=window.setTimeout(video,3000);}
  }
  function button(label,action,extra){
    const b=document.createElement('button');b.type='button';b.textContent=label;
    b.addEventListener('click',async()=>{b.disabled=true;try{await post(action,extra);await loadWorkspaceDevices();}catch(error){status.textContent=error.message;}finally{b.disabled=false;}});
    controls.append(b);return b;
  }
  const start=button('Retomar','start');
  const stop=button('Desligar','stop');
  button('Home','input',{input:{action:'home'}});button(ios?'Recentes':'Voltar','input',{input:{action:ios?'recents':'back'}});
  if(device.root_mode==='stock')button('Play Store','open-store');
  tile.append(header,phone,controls);phoneCanvas.append(tile);
  function update(next){
    device=next;start.hidden=device.online;stop.hidden=!device.online;
    if(device.online){if(!connected)status.textContent='Conectando vídeo…';video();}
    else{cancel();window.clearTimeout(retry);abort?.abort();canvas.hidden=true;placeholder.hidden=false;placeholder.textContent=device.link&& device.link.operation_active===true?device.link.message:device.state==='device'?'Aparelho iniciando…':'Aparelho desligado · dados preservados';status.textContent=device.state==='device'?'INICIANDO':'DESLIGADO';status.dataset.online='false';}
  }
  function dispose(){disposed=true;cancel();window.clearTimeout(retry);abort?.abort();window.removeEventListener('blur',cancel);tile.remove();}
  update(device);return {update,dispose,online:()=>device.online};
}
let workspaceListPromise;
function loadWorkspaceDevices(){
  if(workspaceListPromise)return workspaceListPromise;
  workspaceListPromise=refreshWorkspaceDevices().finally(()=>{workspaceListPromise=undefined;});
  return workspaceListPromise;
}
async function refreshWorkspaceDevices(){
  syncWorkspaceButtons();
  if(devicePlatform!=='android'||!activeLab.id){clearCompanionTiles();workspaceShown='';window.huntmobCanvas?.sync({});return;}
  if(workspaceListBusy)return;workspaceListBusy=true;const workspace=activeLab.id;
  try{
    if(workspaceShown!==workspace){clearCompanionTiles();workspaceShown=workspace;}
    const response=await fetch('/api/workspace/devices?'+new URLSearchParams({workspace}),{cache:'no-store',signal:AbortSignal.timeout(10000)});
    const data=await response.json();if(!response.ok||!data.ok||devicePlatform!=='android'||activeLab.id!==workspace)return;
    window.huntmobSidebar?.companions(data);
    window.huntmobWorkspaceInventory=data;window.huntmobDastDevices?.sync(data);window.huntmobRootPair?.sync(data);
    const visible=data.devices.filter(d=>d.state!=='offline'||d.link?.kind==='root-companion');
    const ids=new Set(visible.map(d=>d.id));
    for(const [id,tile] of companionTiles)if(!ids.has(id)){tile.dispose();companionTiles.delete(id);}
    for(const device of visible){if(companionTiles.has(device.id))companionTiles.get(device.id).update(device);else companionTiles.set(device.id,companionTile(device,workspace));}
    phoneCanvas.classList.toggle('has-companions',companionTiles.size>0);
    window.huntmobCanvas?.sync(data);
  }catch(error){console.info('Inventário de aparelhos indisponível:',error.name);}
  finally{workspaceListBusy=false;syncWorkspaceButtons();}
}
let workspaceIosCatalog;
function syncWorkspaceIosModels(){
  const select=document.querySelector('#workspaceIosModel'),runtime=document.querySelector('#workspaceIosRuntime').value;
  const parts=runtime.match(/iOS-(\d+)-(\d+)(?:-(\d+))?$/),number=parts?Number(parts[1])*65536+Number(parts[2])*256+Number(parts[3]||0):-1;
  const previous=select.value;select.replaceChildren();
  for(const model of workspaceIosCatalog?.models||[]){const option=new Option(window.huntmobIosModels.label(model,number),model.id);option.disabled=number<model.minimum||number>model.maximum;select.add(option);}
  const compatible=Array.from(select.options).filter(o=>!o.disabled);
  select.value=compatible.find(o=>o.value===previous)?.value||compatible[0]?.value||'';
  document.querySelector('#createWorkspaceDevice').disabled=workspaceDeviceBusy||!compatible.length;
  window.huntmobIosModels.render(document.querySelector('#workspaceLegacyModels'),workspaceIosCatalog);
}
async function updateWorkspaceDevicePlatform(){
  const ios=document.querySelector('#workspaceDevicePlatform').value==='ios';
  document.querySelector('#workspaceIosFields').hidden=!ios;
  document.querySelector('#workspaceAndroidProfileField').hidden=ios;
  document.querySelector('#createWorkspaceDevice').disabled=workspaceDeviceBusy||ios;
  const plan=document.querySelector('#workspaceDevicePlan');
  if(!ios){const mode=document.querySelector('#workspaceAndroidProfile').value||activeLab.root_mode;plan.textContent=`Android API ${activeLab.android_api||35} · ${mode==='stock'?'Google Play sem root':'AOSP com ADB root; Magisk opcional, sem Play Store'}. Perfil independente do principal. Apps, contas e dados começam vazios.`;return;}
  plan.textContent='iPhone separado no Mac, ao lado dos Androids. Apps, contas e dados próprios. Requer build .app para Simulator.';
  try{const response=await fetch('/api/ios/catalog',{cache:'no-store'});const data=await response.json();if(document.querySelector('#workspaceDevicePlatform').value!=='ios')return;workspaceIosCatalog=data;
    const version=document.querySelector('#workspaceIosRuntime');version.replaceChildren();for(const runtime of data.runtimes||[])version.add(new Option(runtime.name,runtime.id));
    syncWorkspaceIosModels();if(!data.runtimes?.length)plan.textContent='Prepare uma versão em Gerenciar versões de iOS antes de criar o iPhone.';
  }catch(error){plan.textContent='Não foi possível consultar o catálogo iOS do worker.';}
}
document.querySelector('#workspaceDevicePlatform').addEventListener('change',updateWorkspaceDevicePlatform);
document.querySelector('#workspaceAndroidProfile').addEventListener('change',updateWorkspaceDevicePlatform);
document.querySelector('#workspaceIosRuntime').addEventListener('change',syncWorkspaceIosModels);
document.querySelector('#addWorkspaceDevice').addEventListener('click',()=>{
  if(workspaceDeviceBusy||devicePlatform!=='android')return;
  document.querySelector('#workspaceDeviceStatus').textContent='';
  void updateWorkspaceDevicePlatform();
  document.querySelector('#workspaceDeviceDialog').showModal();
});
document.querySelector('#createWorkspaceDevice').addEventListener('click',async()=>{
  if(workspaceDeviceBusy)return;const workspace=activeLab.id;
  workspaceDeviceBusy=true;syncWorkspaceButtons();const button=document.querySelector('#createWorkspaceDevice');button.disabled=true;
  const platform=document.querySelector('#workspaceDevicePlatform').value;
  const output=document.querySelector('#workspaceDeviceStatus');output.textContent='Criando e iniciando outro aparelho. O principal continua ligado…';
  try{await authorizedPost('/api/workspace/device/action',{action:'create',workspace_id:workspace,platform,root_mode:platform==='android'?(document.querySelector('#workspaceAndroidProfile').value||activeLab.root_mode||'root'):null,runtime:document.querySelector('#workspaceIosRuntime').value,model:document.querySelector('#workspaceIosModel').value});document.querySelector('#workspaceDeviceDialog').close();await loadWorkspaceDevices();notify('Outro aparelho aberto no mesmo workspace.');}
  catch(error){output.textContent=error.message;if(error.payload?.device_created){document.querySelector('#workspaceDeviceDialog').close();await loadWorkspaceDevices();notify('Aparelho criado. Use Retomar para concluir o boot.');}}
  finally{workspaceDeviceBusy=false;button.disabled=false;syncWorkspaceButtons();}
});
document.querySelector('#connectWorkspaceAgent').addEventListener('click',async()=>{
  try{const response=await fetch('/api/workspace/agent?'+new URLSearchParams({workspace:activeLab.id}),{cache:'no-store'});const data=await response.json();if(!data.ok)throw new Error('Configuração indisponível.');workspaceAgentConfig=JSON.stringify(data.config,null,2);document.querySelector('#workspaceAgentConfig').textContent=workspaceAgentConfig;document.querySelector('#workspaceAgentStatus').textContent='Pronto para configurar no seu cliente MCP.';document.querySelector('#workspaceAgentDialog').showModal();}
  catch(error){notify(error.message);}
});
document.querySelector('#copyWorkspaceAgent').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(workspaceAgentConfig);document.querySelector('#workspaceAgentStatus').textContent='Configuração copiada.';}catch{document.querySelector('#workspaceAgentStatus').textContent='Selecione e copie a configuração acima.';}});
everyVisible(loadWorkspaceDevices,5000);everyVisible(syncWorkspaceButtons,1000);loadWorkspaceDevices();

// Pair controls use stable workspace/device identities and background job progress.
(() => {
  const dialog=document.querySelector('#rootPairDialog'),start=document.querySelector('#startRootPair');
  let inventory,pairId,dialogWorkspace,busy=false,lastError='',serviceError='';
  const pair=()=>inventory?.workspace_id===activeLab.id?inventory.devices.find(d=>pairId?d.id===pairId:d.link?.kind==='root-companion'):null;
  const running=d=>d?.link?.operation_active===true;
  function render(){
    if(!dialog.open)return;
    if(dialogWorkspace!==activeLab.id){dialog.close();return;}
    const d=pair();
    document.querySelector('#rootPairPlan').textContent=`Principal API ${activeLab.android_api||'—'} preservado → AOSP API 35 com ADB root, sem Play Store. A versão Android também muda neste par.`;
    document.querySelector('#rootPairStatus').textContent=lastError||d?.link?.message||'Crie o companheiro para comparar os dois ambientes lado a lado.';
    const list=document.querySelector('#rootPairApps');list.replaceChildren();
    for(const app of d?.link?.apps||[]){const item=document.createElement('li'),name=document.createElement('strong'),status=document.createElement('small');name.textContent=app.package_id;status.textContent=app.state==='verified'?`${app.files.length} APK(s) · SHA256 verificado`:app.reason||'Pendente';item.dataset.state=app.state;item.append(name,status);list.append(item);}
    document.querySelector('#rootPairNetwork').textContent=d?.link?.network?d.link.network.reason+(d.link.network.transport==='shared-emulator-wifi'?' A rede Wi-Fi virtual é compartilhada pelos emuladores do host.':' A verificação não deixa portas de teste abertas.'):'A rede será verificada com uma conexão TCP temporária entre os aparelhos.';
    start.textContent=running(d)?'Operação em andamento…':d?'Sincronizar apps novamente':'Criar par e sincronizar';start.disabled=busy||running(d);
    document.querySelector('#rootPairScope').disabled=busy||running(d);
    const net=document.querySelector('#checkRootPairNetwork');net.hidden=!d;net.disabled=busy||running(d)||!d?.online;
    const service=d?.link?.service,serviceToggle=document.querySelector('#pairServiceToggle');document.querySelector('#rootPairService').hidden=!d;serviceToggle.disabled=busy||running(d)||!d?.online;serviceToggle.textContent=service?.enabled?'Desativar conexão TCP':'Ativar conexão TCP';
    for(const [id,value]of [['pairServicePort',service?.service_port],['pairAccessPort',service?.access_port]]){const input=document.querySelector('#'+id);input.disabled=busy||running(d)||!!service?.enabled;if(value)input.value=value;}
    document.querySelector('#pairServiceStatus').textContent=serviceError||(service?.enabled?`Principal 127.0.0.1:${service.access_port} → companheiro:${service.service_port} · TCP`:'Conexão desativada. Ative quando houver um serviço para conectar.');
    const dast=document.querySelector('#rootPairDast');dast.hidden=!d;dast.disabled=busy||running(d)||!d?.online||!d?.apk_sha256;
  }
  function open(id){inventory=window.huntmobWorkspaceInventory;pairId=id;lastError=serviceError='';dialogWorkspace=activeLab.id;dialog.showModal();render();}
  document.querySelector('#createRootCompanion').addEventListener('click',()=>open());
  document.querySelector('#closeRootPair').addEventListener('click',()=>dialog.close());
  async function run(action){
    if(busy||dialogWorkspace!==activeLab.id)return;busy=true;lastError='';render();
    try{const d=pair(),result=await authorizedPost('/api/workspace/device/action',{action,workspace_id:dialogWorkspace,...(d?{device_id:d.id}:{}),app_scope:document.querySelector('#rootPairScope').value});pairId=result.device?.id;await loadWorkspaceDevices();}
    catch(error){lastError=error.message;}
    finally{busy=false;render();}
  }
  start.addEventListener('click',()=>run(pair()?'sync-pair':'create-root-pair'));
  document.querySelector('#checkRootPairNetwork').addEventListener('click',()=>run('check-pair-network'));
  document.querySelector('#pairServiceToggle').addEventListener('click',async()=>{if(busy||dialogWorkspace!==activeLab.id)return;const d=pair();if(!d)return;busy=true;serviceError='';render();try{const result=await authorizedPost('/api/workspace/device/action',{action:'pair-service',workspace_id:dialogWorkspace,device_id:d.id,service_port:Number(document.querySelector('#pairServicePort').value),access_port:Number(document.querySelector('#pairAccessPort').value),enabled:!d.link?.service?.enabled});notify(result.reason);await loadWorkspaceDevices();}catch(error){serviceError=error.message;}finally{busy=false;render();}});
  document.querySelector('#rootPairDast').addEventListener('click',()=>{const d=pair();if(d){dialog.close();window.huntmobDastDevices.select(d.id);}});
  window.huntmobRootPair={open,sync(data){inventory=data;render();}};
})();
