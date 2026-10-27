(() => {
  const select=document.querySelector('#toolsDeviceTarget');let inventory,selected='primary',bioBusy=false,autoCount=0,bioScope,rootBusy=false,rootPending,rootReading=false,rootState,rootScope,rootMessage='';
  const extra=()=>devicePlatform==='android'&&selected!=='primary';
  const target=()=>extra()?inventory?.devices.find(d=>d.id===selected):null;
  const isIos=()=>extra()?target()?.platform==='ios':devicePlatform==='ios';
  const online=()=>extra()?target()?.online:devicePlatform==='ios'?iosInfo?.state==='on':runtimeDevice?.state==='on';
  const id=()=>extra()?selected:devicePlatform==='ios'?iosInfo?.lab?.udid:activeLab.id;
  async function control(payload){if(extra())return authorizedPost('/api/workspace/device/action',{action:'control',workspace_id:inventory.workspace_id,device_id:selected,control:payload});if(isIos())return authorizedPost('/api/ios/action',{...payload,action:'device-control',control:payload.action});return authorizedPost('/api/device/control',{...payload,expected_device_id:activeLab.id});}
  function capabilities(){const ios=isIos(),on=online();document.querySelector('#toolsDeviceIdentity').textContent=(extra()?window.huntmobCanvas?.label(selected):'Principal')+' · '+(extra()?target()?.serial:document.querySelector('#stageSerial').textContent)+' · '+(on?'Online':'Desligado');
    for(const b of document.querySelectorAll('#tab-device-tools .device-controls button')){const support=window.huntmobToolSupport.control(b,ios);b.hidden=support.state==='android';b.disabled=!on||support.state==='android'||(extra()&&b.id==='quickScreenshot');}
    document.querySelector('#iosToolsNote').hidden=!ios;
    document.querySelector('#iosUnavailableControls').hidden=!ios;
    document.querySelector('.tools-analysis-shortcuts').hidden=ios;
    document.querySelector('#quickRootHelp').hidden=ios;
    document.querySelector('#toolsBackDevice').hidden=ios;document.querySelector('#toolsBackDevice').disabled=!on||ios;document.querySelector('#toolsStopDevice').disabled=!on;const stock=extra()?target()?.root_mode==='stock':activeLab.root_mode==='stock';document.querySelector('#toolsStoreDevice').hidden=ios||!stock;
    const rootButton=document.querySelector('#quickRoot'),state=rootScope===id()?rootState:null;
    const rootCapability=window.huntmobToolSupport.appRoot(state,stock);
    document.querySelector('#quickRootLabel').textContent=ios?'Jailbreak':rootBusy?(rootPending?'Ativando root…':'Desativando root…'):state?.enabled?'Root apps · ativo':state&&!state.available?'Root apps · indisponível':state?'Root apps · inativo':'Root apps · verificando';
    rootButton.setAttribute('aria-pressed',String(!ios&&!!state?.enabled));
    rootButton.disabled=!on||ios||rootBusy||rootCapability.disabled;
    select.disabled=rootBusy;
    const progress=document.querySelector('#rootProgress');progress.hidden=!rootBusy||extra()||ios;document.querySelector('#rootProgressTitle').textContent=rootPending?'Ativando Magisk no mesmo Android':'Desativando Magisk';
    const reason=ios?'Jailbreak indisponível no Apple Simulator.':rootCapability.reason;
    rootButton.title=reason;document.querySelector('#quickRootHelp').textContent=rootMessage||reason;

  }
  function sync(data){if(data?.workspace_id)inventory=data;const previous=selected;select.replaceChildren(new Option('Principal'+(devicePlatform==='ios'?' · iOS':' · Android'),'primary'));
    if(devicePlatform==='android')for(const d of inventory?.devices||[])if(d.online)select.add(new Option(window.huntmobCanvas?.label(d.id)||d.serial,d.id));selected=[...select.options].some(o=>o.value===previous)?previous:'primary';select.value=selected;capabilities();}
  select.addEventListener('change',()=>{selected=select.value;rootState=undefined;rootScope=undefined;rootMessage='';document.querySelector('#automaticBiometric').checked=false;autoCount=0;capabilities();refreshRoot();});
  window.huntmobTools={extra,isIos,control,sync,refreshCapabilities:capabilities,rootChanging:()=>rootBusy&&!extra()?rootScope:undefined,refreshRoot:()=>{if(rootScope!==id())refreshRoot();},select(deviceId){selected=deviceId===activeLab.id?'primary':deviceId;sync(inventory);refreshRoot();document.querySelector('[data-tab="device-tools"]').click();}};
  document.querySelector('#checkPentestReadiness').addEventListener('click',async event=>{
    const scope=id(),button=event.currentTarget,status=document.querySelector('#pentestReadinessStatus'),checks=document.querySelector('#pentestReadinessChecks');
    button.disabled=true;status.textContent='Conferindo requisitos deste aparelho…';checks.replaceChildren();
    const query=new URLSearchParams({platform:isIos()?'ios':'android'});
    if(extra())query.set('workspace',inventory.workspace_id),query.set('device',selected);
    try{
      const response=await fetch('/api/pentest/readiness?'+query,{cache:'no-store',signal:AbortSignal.timeout(30000)}),data=await response.json();
      if(scope!==id())return;
      if(!response.ok||!data.ok)throw new Error(data.reason||'Diagnóstico indisponível.');
      status.textContent='Requisitos conferidos · '+new Date(data.checked_at).toLocaleTimeString('pt-BR');
      for(const item of data.checks){const row=document.createElement('div');row.dataset.state=item.state==='ready'?'passed':'blocked';const marker=document.createElement('span');marker.textContent={ready:'OK',blocked:'BLOCK',pending:'PEND',experimental:'BETA',unsupported:'LIMITE'}[item.state]||item.state;const copy=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('small');title.textContent=item.label;detail.textContent=item.detail;copy.append(title,detail);row.append(marker,copy);checks.append(row);}
    }catch(error){if(scope===id())status.textContent=error.name==='TimeoutError'?'A verificação demorou. Confira a conexão e tente novamente.':error.message;}
    finally{button.disabled=false;}
  });
  select.addEventListener('change',()=>{document.querySelector('#pentestReadinessChecks').replaceChildren();document.querySelector('#pentestReadinessStatus').textContent='Aparelho alterado. Verifique os requisitos novamente.';});
  document.querySelector('#toolsBackDevice').addEventListener('click',()=>applyDeviceControl({action:'back'}));
  document.querySelector('#toolsStopDevice').addEventListener('click',async()=>{if(devicePlatform==='android'){if(!extra())return openLabShutdown();return window.huntmobCanvas?.stop([id()]);}try{await authorizedPost('/api/ios/action',{action:'stop'});await loadIosRuntime();}catch(error){notify(error.message);}});
  document.querySelector('#toolsStoreDevice').addEventListener('click',async()=>{try{if(extra())await authorizedPost('/api/workspace/device/action',{workspace_id:inventory.workspace_id,device_id:selected,action:'open-store'});else await deviceAction('open-play-store');}catch(error){notify(error.message);}});
  async function refreshRoot(){const scope=id();if(isIos()||!online()||rootBusy||rootReading)return;if(rootScope!==scope)rootMessage='';rootReading=true;try{const result=await control({action:'app-root-status'});if(scope!==id())return;rootScope=scope;rootState=result.root;}catch(error){if(scope===id()){rootScope=scope;rootState=undefined;rootMessage=error.message;}}finally{rootReading=false;capabilities();}}
  document.querySelector('#quickRoot').addEventListener('click',async()=>{
    if(isIos()||rootBusy||rootScope!==id()||!rootState)return;
    const scope=id(),enabled=!rootState.enabled;
    if(enabled&&!rootState.available){rootMessage='Esta imagem não permite Magisk no mesmo AVD.';notify(rootMessage);capabilities();return;}
    rootBusy=true;rootPending=enabled;rootMessage=(enabled?'Ativando':'Desativando')+' Magisk no mesmo Android; aguardando os processos Android e confirmação do daemon…';capabilities();
    try{
      const result=await control({action:'app-root-toggle',enabled});if(scope!==id())return;rootState=result.root;rootScope=scope;rootMessage=result.message||'Estado do Magisk confirmado.';notify(rootMessage);
    }
    catch(error){if(scope===id()){rootMessage=error.message;notify(error.message);}}
    finally{rootBusy=false;rootPending=undefined;capabilities();if(scope===id()&&!extra())loadRuntime();}
  });
  // Keep fixture scope explicit, and never equate console delivery with app approval.
  function paintBio(bio){const status=document.querySelector('#biometricStatus'),observed=bio.pending_observed;const count=bio.enrolled_count;
    status.textContent=!bio.supported?'Sensor fingerprint indisponível nesta imagem.':!observed?'Sensor disponível · não foi possível ler o pedido pendente.':bio.pending==='enrollment'?'Cadastro de digital em andamento · aguardando toque':bio.pending==='authentication'?'Autenticação em andamento · aguardando toque':`Sem pedido pendente · ${count===null?'cadastro não identificado':count+' digital(is) cadastrada(s)'}`;
    status.className='face-status '+(bio.pending?'ready':'');for(const b of document.querySelectorAll('[data-biometric]'))b.disabled=!['recognized','unrecognized'].includes(b.dataset.biometric)||!bio.supported||!bio.pending||(b.dataset.biometric==='unrecognized'&&bio.pending==='enrollment');
    const automatic=document.querySelector('#automaticBiometric');automatic.disabled=bio.pending!=='enrollment';if(automatic.disabled)automatic.checked=false;
    document.querySelector('#biometricHelp').textContent=bio.pending==='enrollment'?'Use o mesmo ID nas leituras do cadastro. O bloqueio de tela é configurado pelo próprio usuário no Android.':bio.pending==='authentication'?'Use o ID cadastrado para correspondência ou “outra digital” para testar rejeição. Confira o resultado no app.':'Cadastre uma digital em Configurações → Segurança ou abra o prompt no app. Os cenários Sensor sujo, Leitura parcial, Qualidade insuficiente e Rápido demais não são oferecidos pelo console nativo.';
  }
  async function refresh(){if(!document.querySelector('#fixtureDialog').open||document.querySelector('#deviceBiometric').hidden||isIos()||bioBusy)return;if(!bioScope)bioScope=id();if(bioScope!==id()){document.querySelector('#biometricStatus').textContent='O aparelho selecionado mudou. Feche e abra Biometria novamente.';document.querySelector('#automaticBiometric').checked=false;document.querySelectorAll('[data-biometric]').forEach(b=>b.disabled=true);return;}bioBusy=true;const before=id();try{const data=await control({action:'biometric-status'});if(before!==id())return;paintBio(data.biometrics);if(document.querySelector('#automaticBiometric').checked&&data.biometrics.pending==='enrollment'&&autoCount<20){autoCount++;await touch(false);if(autoCount>=20){document.querySelector('#automaticBiometric').checked=false;notify('Limite de 20 toques atingido. Confira o cadastro no Android.');}}}catch(error){document.querySelector('#biometricStatus').textContent=error.message;document.querySelectorAll('[data-biometric]').forEach(b=>b.disabled=true);}finally{bioBusy=false;}}
  async function touch(other){if(bioScope!==id())throw new Error('O aparelho selecionado mudou. Abra Biometria novamente.');const finger=other?65535:Number(document.querySelector('#biometricFingerId').value);if(!Number.isInteger(finger)||finger<1||finger>65535)return notify('Informe um ID de 1 a 65534.');const data=await control({action:'biometric-touch',finger_id:finger});document.querySelector('#biometricStatus').textContent=data.message;return data;}
  for(const b of document.querySelectorAll('[data-biometric]'))b.addEventListener('click',async()=>{if(bioBusy)return;bioBusy=true;b.disabled=true;try{await touch(b.dataset.biometric==='unrecognized');}catch(error){document.querySelector('#biometricStatus').textContent=error.message;}finally{bioBusy=false;}});
  document.querySelector('#automaticBiometric').addEventListener('change',()=>{autoCount=0;});document.querySelector('#fixtureDialog').addEventListener('close',()=>{document.querySelector('#automaticBiometric').checked=false;autoCount=0;bioScope=undefined;});
  window.huntmobBiometrics={refresh};setInterval(refresh,1500);setInterval(capabilities,1500);setInterval(refreshRoot,15000);sync();refreshRoot();
})();
