let iosInfo;
let iosPollBusy=false, iosActionBusy=false;
let iosRenderPending=false;
let iosScreenIdentity='';
function updateIosControls() {
  syncIosDeviceControls();
  const online=iosInfo?.state==='on', ready=iosInfo?.ready===true;
  document.querySelector('#startIos').disabled=iosActionBusy || !ready || online;
  document.querySelector('#startIos').textContent=iosInfo?.lab?.udid?'Retomar Simulator salvo':'Iniciar Simulator';
  document.querySelector('#stopIos').disabled=iosActionBusy || !online;
  document.querySelector('#captureIos').disabled=iosActionBusy || !online;
  document.querySelector('#fixtureIos').disabled=iosActionBusy || !ready;
  document.querySelector('#installIos').disabled=iosActionBusy || !online || !document.querySelector('#iosAppFile').files.length || !document.querySelector('#iosAppApproval').checked;
}
function renderIosNativeReadiness(info) {
  const native=info.virtual_runtime;
  document.querySelector('#iosNativeState').textContent=native?.label || 'Não disponível';
  document.querySelector('#iosNativeState').dataset.state=native?.state==='blocked'?'blocked':'unavailable';
  document.querySelector('#iosNativeSummary').textContent=native?.summary || 'Não foi possível consultar a preparação do iOS virtual.';
  document.querySelector('#iosNativeValidation').textContent=native?.last_validation?`Última validação local: ${native.last_validation}. As etapas observadas não estabelecem um boot completo.`:'Nenhuma validação local disponível.';
  const stages=document.querySelector('#iosNativeStages');
  stages.replaceChildren();
  const labels={observed:'Observado',blocked:'Pendente',pending:'Não validado'};
  for(const stage of native?.stages || []) {
    const row=document.createElement('li');
    row.dataset.state=['observed','blocked','pending'].includes(stage.state)?stage.state:'pending';
    const title=document.createElement('span');title.textContent=stage.label;
    const state=document.createElement('span');state.textContent=labels[stage.state] || labels.pending;
    row.append(title,state);stages.append(row);
  }
}
async function loadIosRuntime(render=false) {
  if(render)iosRenderPending=true;
  if (iosPollBusy) return;
  iosPollBusy=true;
  try {
    const response=await fetch('/api/ios/status',{cache:'no-store'});
    if(!response.ok)throw new Error('Inventário iOS indisponível');
    iosInfo=await response.json();renderIosNativeReadiness(iosInfo);updateIosControls();
    const online=iosInfo.state==='on';
    document.querySelector('#iosDeviceName').textContent='iOS · Simulator';
    document.querySelector('#iosDeviceMeta').textContent=iosInfo.runtimes?.[0]?.name || iosInfo.reason || 'Runtime iOS ausente';
    document.querySelector('#iosAvailability').textContent=online?'1 online':iosInfo.ready?'Simulator pronto':'Ausente';
    document.querySelector('#iosDeviceDot').className=online?'online-dot':'offline-dot';document.querySelector('#iosDeviceDot').setAttribute('aria-label',online?'Online':'Offline');
    document.querySelector('#iosWorkerStatus').textContent=iosInfo.ready?'Apple Simulator disponível':'Runtime iOS ausente';
    document.querySelector('#iosWorkerHelp').textContent=iosInfo.input_ready?'Vídeo e input local prontos':'Xcode + bridge iOS necessários';
    document.querySelector('#iosState').textContent=online?'Ligado':iosInfo.ready?'Desligado':'Indisponível';
    document.querySelector('#iosTarget').textContent=iosInfo.lab?.package_id?`App: ${iosInfo.lab.package_id}${iosInfo.lab.binary_sha256?' · Binário SHA256 '+iosInfo.lab.binary_sha256.slice(0,16):''}`:'Nenhum app selecionado. Abra a fixture ou instale um build autorizado.';
    document.querySelector('#iosIdentityValue').textContent=iosInfo.identity?.value || 'Identificador indisponível';
    document.querySelector('#iosIdentityReason').textContent=iosInfo.identity?.reason || 'Identidade não validada.';
    const shouldRender=render || iosRenderPending;iosRenderPending=false;
    if(!shouldRender || devicePlatform!=='ios') return;
    runtimeDevice=online?{state:'on',platform:'ios'}:undefined;
    renderEngagement(iosInfo.lab);
    document.querySelector('#runtimeState').textContent=online?'ONLINE':'STOPPED';
    document.querySelector('#stageDeviceName').textContent=iosInfo.lab?.package_id || iosInfo.lab?.model?.replace('com.apple.CoreSimulator.SimDeviceType.','').replaceAll('-',' ') || 'iOS Simulator';
    document.querySelector('#stageSerial').textContent=iosInfo.runtimes?.[0]?.name || 'Apple Simulator';
    document.querySelector('#deviceViewport').classList.toggle('runtime-unavailable',!online);
    document.querySelector('#runtimePlaceholder').hidden=online;
    document.querySelector('#runtimePlaceholder strong').textContent='iOS Simulator desligado';
    document.querySelector('#runtimePlaceholder span').textContent=iosInfo.reason || 'Inicie o iOS no painel do laboratório.';
    document.querySelectorAll('.toolbar-actions button').forEach(button=>{button.disabled=true;});
    document.querySelector('#captureEvidence').disabled=!online;
    document.querySelector('#reconnectScreen').disabled=!online;
    document.querySelector('#openDeviceKeyboard').disabled=!online;
    document.querySelector('#openViewer').disabled=!online;
    if(online && iosScreenIdentity!==iosInfo.lab?.udid){stopDeviceScreen();runtimeWasOnline=false;iosScreenIdentity=iosInfo.lab?.udid || '';}
    if(online&&(!runtimeWasOnline || !screenConnected))startDeviceScreen();
    if(!online&&runtimeWasOnline)stopDeviceScreen();
    runtimeWasOnline=online;
    document.querySelector('#eventKind').textContent=online?'IOS':'STATE';
    document.querySelector('#eventMessage').textContent=online?'Apple Simulator real · build para Simulator':'Aguardando iOS';
    document.querySelector('#eventReceipt').textContent=iosInfo.lab?.udid?.slice(0,8)||'sem device';
  } catch(error) {
    iosInfo=undefined;iosRenderPending=false;updateIosControls();
    document.querySelector('#iosWorkerStatus').textContent='Worker iOS indisponível';renderIosNativeReadiness({});
    if(devicePlatform==='ios') {
      runtimeDevice=undefined;runtimeWasOnline=false;stopDeviceScreen();
      document.querySelector('#runtimeState').textContent='UNAVAILABLE';
      document.querySelector('#deviceViewport').classList.add('runtime-unavailable');
      document.querySelector('#runtimePlaceholder').hidden=false;
      document.querySelector('#runtimePlaceholder strong').textContent='Worker iOS indisponível';
      document.querySelector('#runtimePlaceholder span').textContent='Reconecte ao worker para consultar o estado do dispositivo.';
    }
  }
  finally {iosPollBusy=false;window.huntmobSidebar?.ios(iosInfo);}
}
async function switchDevicePlatform(platform) {
  if(devicePlatform===platform)return;
  stopDeviceScreen();runtimeWasOnline=false;runtimeDevice=undefined;devicePlatform=platform;
  if(platform==='ios'){if(typeof clearCompanionTiles==='function')clearCompanionTiles();window.huntmobCanvas?.sync({});}
  document.querySelectorAll('.toolbar-actions button').forEach(button=>{button.disabled=true;});
  document.querySelector('#runtimeState').textContent='PROBING';
  document.querySelector('#stageDeviceName').textContent=platform==='ios'?'Emulador iOS':'HuntMob Android';
  document.querySelector('#stageSerial').textContent='Conectando ao worker…';
  document.querySelector('#deviceScreen').alt=platform==='ios'?'Tela interativa do iOS Simulator: toque e arraste':'Tela interativa do Android HuntMob: toque e arraste';
  document.querySelector('#deviceVideo').setAttribute('aria-label',platform==='ios'?'Tela interativa do iOS Simulator':'Tela interativa do Android');
  document.querySelector('#workspace').classList.toggle('ios-view',platform==='ios');
  syncIosDeviceControls();
  document.querySelector('#iosDevice').classList.toggle('selected',platform==='ios');
  document.querySelector('#runtimeDevice').classList.toggle('selected',platform==='android');
  document.querySelectorAll('.analysis-tabs button').forEach(button=>{button.disabled=false;});
  if(platform==='ios') {document.querySelector('[data-tab="device-tools"]').click();document.querySelector('#deviceProfileDetails').open=true;await loadIosRuntime(true);}
  else {document.querySelector('[data-tab="reverse"]').click();await loadRuntime();}
  loadEvidence();
}
function startIosScreen(generation) {
  const screen=document.querySelector('#deviceScreen');
  document.querySelector('.phone-screen').hidden=true;
  screen.onload=()=>{
    if(generation!==screenGeneration||devicePlatform!=='ios')return;
    screenRetries=0;
    screen.hidden=false;screen.dataset.frameWidth=screen.naturalWidth;screen.dataset.frameHeight=screen.naturalHeight;
    fitPhoneFrame(screen,screen.naturalWidth,screen.naturalHeight,'ios');
    document.querySelector('#screenConnection').textContent='iOS · vídeo até 60 fps · toque contínuo';
  };
  screen.onerror=()=>{
    if(generation!==screenGeneration||devicePlatform!=='ios'||runtimeDevice?.state!=='on')return;
    screen.hidden=true;
    if(screenRetries>=5){document.querySelector('#screenConnection').textContent='Vídeo iOS indisponível · use Reconectar tela';return;}
    const delay=Math.min(5000,500*2**screenRetries++);
    document.querySelector('#screenConnection').textContent=`Reconectando vídeo iOS em ${delay/1000}s…`;
    screenTimer=window.setTimeout(()=>{
      if(generation===screenGeneration&&devicePlatform==='ios'&&runtimeDevice?.state==='on')startDeviceScreen();
    },delay);
  };
  if(typeof window.createImageBitmap==='function'){
    startIosCanvas(generation,(width,height)=>{
      screenRetries=0;screen.dataset.frameWidth=width;screen.dataset.frameHeight=height;
      document.querySelector('#screenConnection').textContent='iOS · toque contínuo';
    },()=>screen.onerror?.());
    return;
  }
  screen.src='/api/ios/stream?t='+Date.now();
}
async function iosAction(action) {
  if(iosActionBusy)return;
  iosActionBusy=true;
  updateIosControls();
  document.querySelector('#iosActionStatus').textContent='Executando no Simulator…';
  try {
    const result=await authorizedPost('/api/ios/action',{action});
    document.querySelector('#iosActionStatus').textContent=action==='capture'?'Evidência iOS salva e verificada.':action==='fixture'?'Fixture local instalada e aberta.':'Operação concluída no Simulator.';
    await loadIosRuntime(devicePlatform==='ios');if(action==='capture')loadEvidence();
  }catch(error){document.querySelector('#iosActionStatus').textContent=error.message;notify(error.message);}
  finally{iosActionBusy=false;updateIosControls();}
}
window.addEventListener('DOMContentLoaded',()=>{
  document.querySelector('#iosDevice').addEventListener('click',()=>switchDevicePlatform('ios'));
  document.querySelector('#runtimeDevice').addEventListener('click',()=>switchDevicePlatform('android'));
  document.querySelector('#startIos').addEventListener('click',()=>iosAction('start'));
  document.querySelector('#fixtureIos').addEventListener('click',()=>iosAction('fixture'));
  document.querySelector('#captureIos').addEventListener('click',()=>iosAction('capture'));
  document.querySelector('#stopIos').addEventListener('click',()=>iosAction('stop'));
  document.querySelector('#iosAppFile').addEventListener('change',updateIosControls);
  document.querySelector('#iosAppApproval').addEventListener('change',updateIosControls);
  updateIosControls();
  document.querySelector('#installIos').addEventListener('click',async()=>{
    if(iosActionBusy)return;
    const file=document.querySelector('#iosAppFile').files[0];
    if(file && /\.ipa$/i.test(file.name)){
      document.querySelector('#iosActionStatus').textContent='IPA de iPhone físico não é compatível com este Simulator. Solicite ao time do app um build para iOS Simulator (.app compactado em ZIP). Renomear o IPA não converte o binário. O app atual permanece instalado.';
      return;
    }
    if(!file || !document.querySelector('#iosAppApproval').checked){notify('Escolha o ZIP do .app e confirme a autorização.');return;}
    iosActionBusy=true;updateIosControls();
    document.querySelector('#iosActionStatus').textContent='Instalando build no Simulator…';
    try{
      if(!csrfToken)csrfToken=(await fetch('/api/session').then(r=>r.json())).csrf_token;
      const response=await sessionFetch('/api/ios/upload',{method:'POST',headers:{'X-HuntMob-CSRF':csrfToken,'X-HuntMob-Approved':'true','Content-Type':'application/zip'},body:file});
      const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.reason||'Build não instalado.');
      document.querySelector('#iosActionStatus').textContent='App instalado e aberto no iOS Simulator.';await loadIosRuntime(true);
    }catch(error){document.querySelector('#iosActionStatus').textContent=error.message;}
    finally{iosActionBusy=false;updateIosControls();}
  });
  loadIosRuntime(false);
});

window.addEventListener('DOMContentLoaded',()=>{
  document.querySelector('#analyzeIos').addEventListener('click',async()=>{
    const file=document.querySelector('#iosStaticFile').files[0];
    const output=document.querySelector('#iosStaticResult');
    const button=document.querySelector('#analyzeIos');
    if(!file){output.textContent='Selecione um IPA autorizado.';return;}
    button.disabled=true;output.textContent='Analisando localmente…';
    try{
      const response=await sessionFetch('/api/ios/analyze',{method:'POST',headers:{'X-HuntMob-CSRF':csrfToken,'X-HuntMob-Approved':'true','Content-Type':'application/zip'},body:file});
      const result=await response.json();
      if(!result.ok)throw new Error(result.reason||'Análise não concluída.');
      output.textContent=JSON.stringify(result,null,2);
    }catch(error){output.textContent=error.message;}
    finally{button.disabled=false;}
  });
});

function syncIosDeviceControls() {
  const ios=devicePlatform==='ios', online=iosInfo?.state==='on';
  document.querySelectorAll('.device-controls button').forEach(button=>{
    if (!button.dataset.originalTitle) button.dataset.originalTitle=button.title;
    const panel=button.dataset.controlPanel;
    const supported=['location','battery','system','rotation'].includes(panel) || button.dataset.panel==='biometric' || ['home','recents'].includes(button.dataset.deviceKey) || ['proxy','frida'].includes(button.dataset.toolShortcut) || button.id==='quickScreenshot';
    button.disabled=ios && (!online || !supported);
    button.title=ios && !supported?'Indisponível no perfil iOS atual. Requer um runtime compatível.':button.dataset.originalTitle;
    if(ios && button.dataset.panel==='biometric')button.title='Eventos biométricos simulados do iOS';
    if(ios && panel==='rotation')button.title='Orientação do iOS';
    if(ios && panel==='system')button.title='Sistema e navegação iOS';
    if(ios && panel==='battery')button.title='Indicador visual de bateria';
  });
  document.querySelectorAll('[data-control-action]').forEach(button=>{
    button.disabled=ios && (!online || !['location','battery','battery-reset','home','recents','rotation'].includes(button.dataset.controlAction));
  });
  document.querySelectorAll('[data-device-key]').forEach(button=>{button.disabled=ios && (!online || !['home','recents'].includes(button.dataset.deviceKey));});
}

let iosLabCatalog;
let labCatalogGeneration=0;
async function updateLabPlatform() {
  const generation=++labCatalogGeneration;
  const ios=document.querySelector('#labPlatform').value==='ios';
  document.querySelector('#labLegacyModels').hidden=!ios;
  const version=document.querySelector('#labVersion');version.replaceChildren();
  document.querySelector('#labModelField').hidden=!ios;
  document.querySelector('#manageLabIosVersions').hidden=!ios;
  document.querySelector('#labIosAccessField').hidden=!ios;
  document.querySelector('#labRootMode').closest('label').hidden=ios;
  document.querySelector('#labLegacySdk').closest('label').hidden=ios;
  document.querySelector('#labArtifact').value='';document.querySelector('#labArtifact').accept=ios?'.zip':'.apk';
  const source=document.querySelector('#labSource');source.replaceChildren();
  const sources=ios?[['upload','Build .app.zip para Simulator'],['empty','iOS vazio']]:[['upload','APK local · lab exclusivo'],['empty','Android vazio'],['play-manual','Play Store · login no dispositivo']];
  sources.forEach(([value,label])=>source.add(new Option(label,value)));source.value=ios?'empty':'play-manual';
  document.querySelector('#labPackageLabel').textContent=ios?'Bundle ID':'Package ID';
  document.querySelector('#labPackageHelp').textContent=ios?'opcional; detectado do build .app':'opcional; detectado do APK';
  source.dispatchEvent(new Event('change'));
  document.querySelector('#labError').hidden=true;

  if(ios)document.querySelector('#labVersionHelp').textContent='Versões instaladas no worker Mac. iOS virtual e jailbreak ainda indisponíveis.';
  document.querySelector('#createLab').disabled=ios;
  if(!ios) {
    const arch=runtimeDevice?.architecture==='arm64-v8a'?' · ARM64':runtimeDevice?.architecture==='x86_64'?' · x86_64':'';
    [[36,'16'],[35,'15'],[34,'14'],[33,'13'],[32,'12L'],[31,'12'],[30,'11']].forEach(([api,name])=>version.add(new Option('Android '+name+' · API '+api+arch,api)));
    version.value='35';
    return;
  }
  try {
    const response=await fetch('/api/ios/catalog',{cache:'no-store'});const result=await response.json();
    if(generation!==labCatalogGeneration)return;
    if(!result.ok || !result.runtimes.length)throw new Error(result.reason || 'Nenhuma versão iOS disponível neste worker.');
    iosLabCatalog=result;
    result.runtimes.forEach(runtime=>version.add(new Option(runtime.name,runtime.id)));
    try{const available=await fetchIosRuntimeCatalog();if(generation!==labCatalogGeneration)return;appendMissingIosVersions(version,available);}catch{}
    updateLabModels();
  } catch(error) {
    if(generation!==labCatalogGeneration)return;
    version.add(new Option('Nenhum runtime disponível',''));document.querySelector('#labVersionHelp').textContent=error.message;
  }
}
function updateLabModels() {
  if(document.querySelector('#labPlatform').value!=='ios' || !iosLabCatalog)return;
  const runtime=document.querySelector('#labVersion').value;
  const parts=runtime.match(/iOS-(\d+)-(\d+)(?:-(\d+))?$/);
  const encoded=parts?Number(parts[1])*65536+Number(parts[2])*256+Number(parts[3]||0):0;
  const model=document.querySelector('#labModel'),previous=model.value;model.replaceChildren();
  iosLabCatalog.models.forEach(device=>{
    const option=new Option(window.huntmobIosModels.label(device,encoded),device.id);model.add(option);
  });
  const available=iosLabCatalog.models.find(d=>encoded>=d.minimum&&encoded<=d.maximum);
  if(previous && iosLabCatalog.models.some(d=>d.id===previous))model.value=previous;
  else if(available)model.value=available.id;
  window.huntmobIosModels.render(document.querySelector('#labLegacyModels'),iosLabCatalog);
  validateIosModel();
}
function validateIosModel(){
  if(document.querySelector('#labPlatform').value!=='ios')return;
  const runtime=document.querySelector('#labVersion').value,parts=runtime.match(/iOS-(\d+)-(\d+)(?:-(\d+))?$/),encoded=parts?Number(parts[1])*65536+Number(parts[2])*256+Number(parts[3]||0):0;
  const device=iosLabCatalog?.models.find(d=>d.id===document.querySelector('#labModel').value);
  const valid=!!device&&encoded>=device.minimum&&encoded<=device.maximum;
  document.querySelector('#createLab').disabled=!valid;
  const installed=device?(iosLabCatalog.runtimes||[]).filter(runtime=>window.huntmobIosModels.compatible(device,runtime.id)):[];
  document.querySelector('#labModelField small').textContent=valid?'Modelo compatível com a versão selecionada.':device?`${device.name} exige ${window.huntmobIosModels.range(device)}. ${installed.length?'Selecione '+installed.map(runtime=>runtime.name).join(', ')+'.':'Nenhuma versão compatível está instalada neste worker. Use um worker com macOS, Xcode e runtime compatíveis.'}`:'Selecione um modelo disponível.';
}
document.querySelector('#labModel').addEventListener('change',validateIosModel);
document.querySelector('#labPlatform').addEventListener('change',updateLabPlatform);
document.querySelector('#labVersion').addEventListener('change',updateLabModels);

function openIosBiometrics() {
  document.querySelector('#deviceControlForm .eyebrow').textContent='LABORATÓRIO IOS';
  document.querySelector('#controlTitle').textContent='Biometria de teste';
  document.querySelectorAll('[data-control-section]').forEach(section=>{section.hidden=section.dataset.controlSection!=='biometric';});
  document.querySelector('#controlReadback').hidden=true;
  document.querySelector('#controlStatus').textContent='Habilite o cadastro e abra o prompt de autenticação no app do aparelho selecionado.';
  document.querySelector('#deviceControlDialog').showModal();
}
document.querySelectorAll('[data-ios-biometric]').forEach(button=>button.addEventListener('click',()=>applyDeviceControl({action:'biometric',mode:button.dataset.iosBiometric,kind:document.querySelector('#iosBiometricKind').value})));
document.querySelector('#iosFridaInspect').addEventListener('click',async()=>{
  const button=document.querySelector('#iosFridaInspect'),output=document.querySelector('#iosFridaOutput');button.disabled=true;output.textContent='Verificando o binário autorizado e a conexão…';
  try{const result=await authorizedPost('/api/ios/action',{action:'frida-inspect'});output.textContent=JSON.stringify(result.receipt,null,2);}
  catch(error){output.textContent='Conexão não validada: '+error.message;}
  finally{button.disabled=false;}
});
async function refreshIosProxy() {
  if(devicePlatform!=='ios')return;
  try {
    const response=await fetch('/api/ios/proxy/status',{cache:'no-store'});const data=await response.json();
    document.querySelector('#iosProxyState').textContent=data.active?'Listener ativo':'Parado';
    document.querySelector('#iosProxyFlows').textContent=data.flows?.map(flow=>`${flow.method} ${flow.host}${flow.path} · ${flow.status ?? flow.state}`).join('\n') || 'Nenhuma requisição capturada.';
  } catch(error){document.querySelector('#iosProxyState').textContent='Indisponível';}
}
document.querySelectorAll('[data-ios-proxy]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;
  try {const data=await authorizedPost('/api/ios/action',{action:'proxy-'+button.dataset.iosProxy});document.querySelector('#iosProxyStatus').textContent=data.reason || 'Operação concluída.';await refreshIosProxy();}
  catch(error){document.querySelector('#iosProxyStatus').textContent=error.message;}
  finally{button.disabled=false;}
}));
document.querySelector('#iosProxyRefresh').addEventListener('click',refreshIosProxy);
window.setInterval(()=>{if(devicePlatform==='ios' && document.querySelector('#tab-proxy').classList.contains('active'))refreshIosProxy();},2000);

let xtoolBusy=false;
function syncXtoolActions(){
  const allowed=document.querySelector('#xtoolApproval').checked && !!document.querySelector('#xtoolDevice').value && !xtoolBusy;
  document.querySelector('#xtoolInstall').disabled=!allowed || !document.querySelector('#xtoolIpa').files.length;
  document.querySelector('#xtoolLaunch').disabled=!allowed || !document.querySelector('#xtoolBundle').value.trim();
  document.querySelector('#xtoolRefresh').disabled=xtoolBusy;
}
async function refreshXtool(){
  const output=document.querySelector('#xtoolStatus');output.textContent='Consultando o worker…';
  try{
    const data=await fetch('/api/ios/xtool/status',{cache:'no-store'}).then(r=>r.json());
    document.querySelector('#xtoolState').textContent=data.available ? 'Instalado'+(data.version?' · '+data.version:'') : 'Ausente';
    const select=document.querySelector('#xtoolDevice');select.replaceChildren(new Option('Selecione o dispositivo autorizado',''));
    (data.devices || []).forEach(d=>select.add(new Option(`${d.name} · ${d.udid}`,d.udid)));
    document.querySelector('#xtoolApproval').checked=false;output.textContent=data.reason;
  }catch(error){output.textContent='Não foi possível consultar o xtool.';}
  syncXtoolActions();
}
document.querySelector('#xtoolRefresh').addEventListener('click',refreshXtool);
['xtoolApproval','xtoolDevice','xtoolIpa','xtoolBundle'].forEach(id=>document.querySelector('#'+id).addEventListener('input',syncXtoolActions));
document.querySelector('#xtoolDevice').addEventListener('change',()=>{document.querySelector('#xtoolApproval').checked=false;syncXtoolActions();});
document.querySelector('#xtoolInstall').addEventListener('click',async()=>{
  const file=document.querySelector('#xtoolIpa').files[0],output=document.querySelector('#xtoolStatus');
  if(!file || !document.querySelector('#xtoolApproval').checked)return;
  if(file.size>512*1024*1024){output.textContent='IPA deve ter até 512 MB.';return;}
  xtoolBusy=true;syncXtoolActions();output.textContent='Validando IPA e instalando no dispositivo USB selecionado…';
  try{
    if(!csrfToken)csrfToken=(await fetch('/api/session').then(r=>r.json())).csrf_token;
    const response=await sessionFetch('/api/ios/xtool/install',{method:'POST',headers:{'X-HuntMob-CSRF':csrfToken,'X-HuntMob-Approved':'true','X-HuntMob-Device':document.querySelector('#xtoolDevice').value,'Content-Type':'application/zip'},body:file});
    const result=await response.json();output.textContent=result.reason || 'Operação não concluída.';
  }catch(error){output.textContent='Instalação não confirmada. Confira o dispositivo antes de repetir.';}
  finally{xtoolBusy=false;syncXtoolActions();}
});
document.querySelector('#xtoolLaunch').addEventListener('click',async()=>{
  if(!document.querySelector('#xtoolApproval').checked)return;
  xtoolBusy=true;syncXtoolActions();
  const output=document.querySelector('#xtoolStatus');output.textContent='Abrindo app no dispositivo USB selecionado…';
  try{const data=await authorizedPost('/api/ios/action',{action:'xtool-launch',udid:document.querySelector('#xtoolDevice').value,bundle_id:document.querySelector('#xtoolBundle').value.trim()});output.textContent=data.reason;}
  catch(error){output.textContent=error.message;}
  finally{xtoolBusy=false;syncXtoolActions();}
});
