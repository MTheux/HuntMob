// Sidebar presentation reuses observed inventory; it never starts a device.
(() => {
  const state={android:null,androidError:false,ios:null,companions:[],workspace:'',labs:[],current:'',query:'',presentation:{devices:{}}};
  const companionRows=new Map(),openGroups=new Map(),resumeErrors=new Map(),selectedLabs=new Set();
  let selectingLabs=false,labOperationBusy=false,stopRequest=null;
  const $=selector=>document.querySelector(selector);
  const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const matches=value=>normalize(value).includes(normalize(state.query));
  const profile=lab=>lab.root_mode==='stock'?'Google Play':'AOSP';
  const shortId=id=>String(id||'').replace('huntmob_lab_','').slice(0,6);
  const runtimeVersion=value=>String(value||'').replace('com.apple.CoreSimulator.SimRuntime.','').replaceAll('-','.').replace('iOS.','iOS ');
  function label(tag,classes,text){const e=document.createElement(tag);e.className=classes;e.textContent=text;return e;}
  function closeDrawer(){document.body.classList.remove('show-device-list');$('#toggleDeviceList').setAttribute('aria-expanded','false');}
  function deviceState(row,dot,badge,online,pending=false){
    row.dataset.online=String(online);dot.className=online?'online-dot':'offline-dot';
    const text=pending?'Verificando':online?'Online':'Desligado';
    dot.setAttribute('aria-label',text);badge.textContent=text;badge.dataset.online=String(online);
  }
  function renderPrimary(){
    const payload=state.android,device=payload?.devices?.[0],lab=payload?.lab||{};
    const row=$('#runtimeDevice'),available=!!device||!!lab.id;
    row.dataset.sidebarAvailable=String(available);
    if(!payload)return;
    const online=!state.androidError&&device?.state==='on';
    $('#runtimeName').textContent=state.presentation.devices[lab.id]?.label||lab.package_id||device?.name||'Android principal';
    $('#runtimeMeta').textContent=`API ${lab.android_api||device?.api||35} · ${profile(lab)}`;
    row.title=[lab.package_id||'Android principal',device?.adb_serial||'emulator-5556',device?.architecture,lab.id].filter(Boolean).join(' · ');
    row.dataset.sidebarSearch=['Android principal',lab.package_id,lab.id,device?.adb_serial,`API ${lab.android_api||device?.api||35}`,profile(lab)].join(' ');
    deviceState(row,$('#runtimeDot'),$('#runtimeRowState'),online);
    if(state.androidError)$('#runtimeRowState').textContent='Sem conexão';
    $('#runtimeEmpty').hidden=available||!!state.query;
    row.hidden=!available||!matches(row.dataset.sidebarSearch);
  }
  function renderIos(){
    if(state.ios===null)return;
    const info=state.ios,online=info?.state==='on',row=$('#iosDevice');
    const model=info?.lab?.model?.replace('com.apple.CoreSimulator.SimDeviceType.','').replaceAll('-',' ');
    const version=runtimeVersion(info?.lab?.runtime)||info?.runtimes?.[0]?.name||'Simulator';
    $('#iosDeviceName').textContent=model||'iPhone Simulator';
    $('#iosDeviceMeta').textContent=info?.ready?[version,info?.lab?.udid?'ID '+info.lab.udid.slice(0,8):''].filter(Boolean).join(' · '):'Runtime não preparado';
    row.title=info?.lab?.udid?'Selecionar Simulator do worker · '+info.lab.udid:'Selecionar iOS Simulator';
    deviceState(row,$('#iosDeviceDot'),$('#iosRowState'),online,!info);
    if(!info)$('#iosRowState').textContent='Sem conexão';
    $('#sidebarWorkerPlatform').textContent=info?.ready?'Mac':'Local';
    $('#iosAvailability').textContent=online?'1 online':info?.ready?'Disponível':'Indisponível';
    $('#iosWorkerStatus').textContent=info?.ready?'iOS disponível neste worker':info?'iOS não preparado':'Conexão iOS indisponível';
    $('#iosWorkerHelp').textContent=info?.input_ready?'Vídeo e toque disponíveis. Os aparelhos mantêm seus próprios dados.':'Consulte o perfil iOS para conferir runtime, vídeo e toque.';
    row.dataset.sidebarSearch=['iOS iPhone Simulator',model,version,info?.lab?.udid].join(' ');
    row.hidden=!matches(row.dataset.sidebarSearch);
  }
  function makeCompanion(device){
    const row=document.createElement('button');row.type='button';row.className='device-row sidebar-companion';row.dataset.deviceId=device.id;
    const icon=document.createElement('span');icon.className='device-thumb';
    icon.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4m-3 14h2"/></svg>';
    const copy=label('span','sidebar-device-copy',''),heading=label('span','sidebar-row-heading','');
    const badge=label('span','sidebar-device-state','');
    const name=label('strong','',''),meta=label('small','',''),errorText=label('small','sidebar-device-error',''),dot=document.createElement('i');
    heading.append(name,badge);copy.append(heading,meta,errorText);row.append(icon,copy,dot);
    row.addEventListener('click',async()=>{
      if(devicePlatform!=='android')await switchDevicePlatform('android');
      const latest=state.companions.find(d=>d.id===device.id);let resumed=false;
      if(latest?.state==='offline'){row.disabled=true;resumeErrors.delete(device.id);try{await authorizedPost('/api/workspace/device/action',{action:'start',workspace_id:state.workspace,device_id:device.id});resumed=true;await loadWorkspaceDevices();}catch(error){resumeErrors.set(device.id,error.message);renderCompanions();notify(error.message);return;}finally{row.disabled=false;}}
      let tile=document.querySelector(`[data-device-id="${device.id}"].device-tile`);
      if(!tile){await loadWorkspaceDevices();tile=document.querySelector(`[data-device-id="${device.id}"].device-tile`);}
      if(!tile)return notify(resumed?'Aparelho iniciado. Atualizando a tela…':'Aparelho indisponível neste workspace. Atualize o inventário.');
      closeDrawer();tile.scrollIntoView({behavior:'smooth',block:'nearest',inline:'center'});
      tile.tabIndex=-1;tile.focus({preventScroll:true});
    });
    return {row,icon,name,meta,dot,badge,errorText};
  }
  function renderCompanions(){
    // Keep this list aligned with the workspace: stopped frames have been removed.
    const devices=state.companions.filter(device=>device.state!=='offline');
    const ids=new Set(devices.map(d=>d.id));
    for(const [id,item] of companionRows)if(!ids.has(id)){item.row.remove();companionRows.delete(id);}
    for(const device of devices){
      let item=companionRows.get(device.id);
      if(!item){item=makeCompanion(device);companionRows.set(device.id,item);$('#sidebarCompanions').append(item.row);}
      const ios=device.platform==='ios';item.icon.classList.toggle('ios',ios);item.icon.classList.toggle('android',!ios);
      item.name.textContent=state.presentation.devices[device.id]?.label||(ios?(device.model?.replace('com.apple.CoreSimulator.SimDeviceType.','').replaceAll('-',' ')||'iPhone Simulator'):`Android · API ${device.android_api}`);
      const serial=ios?'ID '+device.serial.slice(0,8):device.serial;
      item.meta.textContent=ios?`${runtimeVersion(device.runtime)} · ${serial}`:`${serial} · ${profile(device)}`;
      item.row.title=`${device.state==='offline'?'Retomar aparelho':'Localizar aparelho'} · ${device.serial}`;
      if(device.online)resumeErrors.delete(device.id);item.errorText.textContent=resumeErrors.get(device.id)||'';item.errorText.hidden=!item.errorText.textContent;
      item.row.dataset.sidebarSearch=[ios?'iOS iPhone Simulator':'Android',item.name.textContent,item.meta.textContent,device.serial,device.id].join(' ');
      deviceState(item.row,item.dot,item.badge,device.online===true);
      if(!device.online&&device.state==='device')item.badge.textContent='Iniciando';
      item.row.hidden=!matches(item.row.dataset.sidebarSearch);
    }
  }
  function renderCount(){
    const primary=!state.androidError&&state.android?.devices?.[0]?.state==='on';
    const online=(primary?1:0)+state.companions.filter(d=>d.online).length;
    $('#runtimeCount').textContent=state.android?`${online} online`:'—';
    $('#runtimeCount').dataset.online=String(online>0);
  }
  function labTitle(lab){return lab.package_id||(lab.legacy?'Laboratório anterior':'Sem aplicativo');}
  function labMatches(lab){return matches([labTitle(lab),lab.id,`API ${lab.android_api||35}`,profile(lab),lab.id===state.current?'atual':''].join(' '));}
  function updateLabSelection(){
    const count=selectedLabs.size;
    $('#savedLabSelectionStatus').textContent=!count?'Nenhum lab selecionado.':`${count} lab(s) selecionado(s).`;
    $('#savedLabStopSelected').disabled=labOperationBusy||!count;
    $('#savedLabDeleteSelected').disabled=labOperationBusy||!count;
    $('#savedLabSelectMode').disabled=labOperationBusy;
    $('#savedLabSelectAll').disabled=labOperationBusy;
    $('#savedLabClearSelection').disabled=labOperationBusy||!count;
  }
  async function analyzeLabRea(lab,button){
    const plan=window.huntmobLabRea.labReaPlan(lab,{currentId:state.current});
    if(!plan.allowed)return notify(plan.reason);
    if(labOperationBusy)return;
    if(plan.needsResume&&!window.confirm('Analisar este app exige retomar o lab. O lab atual será desligado e preservado. Continuar?'))return;
    const previous=button.textContent;button.disabled=true;button.textContent='Analisando…';
    try{
      if(plan.needsResume){
        notify('Retomando o lab para extrair e analisar o APK…');
        await authorizedPost('/api/device/action',{action:'resume',lab_id:lab.id});
        await loadRuntime();await loadSavedLabs();
      }
      if(devicePlatform!=='android')await switchDevicePlatform('android');
      closeDrawer();
      if(!window.huntmobStartReaForPackage)throw new Error('Módulo REA ainda não carregado.');
      await window.huntmobStartReaForPackage(plan.package,message=>notify(message));
    }catch(error){notify(error.message);}
    finally{button.disabled=false;button.textContent=previous;}
  }
  function renderLabs(){
    const root=$('#savedLabs');root.replaceChildren();const groups=new Map();let visible=0;
    for(const lab of state.labs){
      const key=lab.package_id||(lab.legacy?'legacy':'empty');
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(lab);
    }
    const sorted=[...groups.entries()].sort(([,a],[,b])=>Number(b.some(l=>l.id===state.current))-Number(a.some(l=>l.id===state.current)));
    for(const [key,labs] of sorted){
      const title=key==='empty'?'Sem aplicativo':key==='legacy'?'Laboratório anterior':key;
      const filtered=labs.filter(labMatches);
      if(!filtered.length)continue;visible+=filtered.length;
      const group=document.createElement('details');group.className='saved-lab-group';
      group.open=state.query?true:(openGroups.get(key)??labs.some(l=>l.id===state.current));
      const summary=document.createElement('summary');summary.append(label('span','saved-group-name',title),label('span','saved-group-count',String(filtered.length)));
      group.append(summary);group.addEventListener('toggle',()=>{if(!state.query)openGroups.set(key,group.open);});
      for(const lab of filtered){
        const current=lab.id===state.current,button=document.createElement('button');button.type='button';button.className='saved-lab';
        button.title=(current?'Laboratório atual · ':'Retomar laboratório · ')+lab.id;
        if(current)button.setAttribute('aria-current','true');
        const heading=label('span','saved-lab-heading','');heading.append(label('strong','',`API ${lab.android_api||35}`),label('span','lab-profile',profile(lab)));
        if(current)heading.append(label('span','current-lab-tag','Atual'));
        button.append(heading,label('small','saved-lab-id',`ID · ${shortId(lab.id)}`));
        const entry=document.createElement('div');entry.className='saved-lab-entry';
        entry.classList.toggle('is-selecting',selectingLabs);entry.classList.toggle('is-selected',selectedLabs.has(lab.id));
        const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.className='saved-lab-select';checkbox.hidden=!selectingLabs;
        checkbox.checked=selectedLabs.has(lab.id);checkbox.setAttribute('aria-label',`Selecionar lab ${title}, API ${lab.android_api||35}, ID ${shortId(lab.id)}`);
        function choose(checked){checkbox.checked=checked;if(checked)selectedLabs.add(lab.id);else selectedLabs.delete(lab.id);entry.classList.toggle('is-selected',checked);updateLabSelection();}
        checkbox.addEventListener('change',()=>choose(checkbox.checked));
        button.addEventListener('click',()=>selectingLabs?choose(!checkbox.checked):resumeSavedLab(lab,button));
        entry.append(checkbox,button);
        if(lab.package_id){const rea=label('button','saved-lab-rea','Analisar app (RE)');rea.type='button';rea.hidden=selectingLabs;rea.title=`Engenharia reversa de ${labTitle(lab)}`;rea.addEventListener('click',event=>{event.stopPropagation();analyzeLabRea(lab,rea);});entry.append(rea);}
        group.append(entry);
      }
      root.append(group);
    }
    $('#savedLabCount').textContent=state.query?`${visible}/${state.labs.length}`:String(state.labs.length);
    if(!state.labs.length)root.append(label('p','runtime-empty','Seus laboratórios aparecerão aqui.'));
    updateLabSelection();
    return visible;
  }
  function filterSections(){
    const querying=!!state.query;
    $('#workspaceDeviceSection').hidden=querying&&![$('#runtimeDevice'),...$('#sidebarCompanions').children].some(row=>!row.hidden);
    $('#workerDeviceSection').hidden=querying&&$('#iosDevice').hidden;
    $('#savedLabSection').hidden=querying&&!$('#savedLabs').querySelector('.saved-lab');
    $('#sidebarSearchEmpty').hidden=!querying||[$('#workspaceDeviceSection'),$('#workerDeviceSection'),$('#savedLabSection')].some(section=>!section.hidden);
  }
  function sync(){renderPrimary();renderIos();renderCount();filterSections();updateLabSelection();}
  window.huntmobSidebar={
    runtime(payload){state.android=payload;state.androidError=false;if(state.workspace!==payload.lab?.id){state.workspace=payload.lab?.id||'';state.companions=[];renderCompanions();}},
    runtimeError(){state.androidError=true;},
    ios(info){state.ios=info;sync();},
    companions(payload){if(payload.workspace_id!==state.workspace)return;state.companions=payload.devices||[];state.presentation=payload.presentation||{devices:{}};renderCompanions();sync();},
    labs(payload){state.labs=payload.labs||[];state.current=payload.current?.id||'';const valid=new Set(state.labs.map(lab=>lab.id));for(const id of selectedLabs)if(!valid.has(id))selectedLabs.delete(id);renderLabs();filterSections();},
    presentation(value){state.presentation=value;renderCompanions();sync();},
    sync,
  };
  $('#deviceSearch').addEventListener('input',event=>{state.query=event.target.value.trim();selectedLabs.clear();renderPrimary();renderIos();renderCompanions();renderLabs();filterSections();});
  $('#savedLabSelectMode').addEventListener('click',()=>{
    if(labOperationBusy)return;
    selectingLabs=!selectingLabs;selectedLabs.clear();
    $('#savedLabSelectMode').textContent=selectingLabs?'Concluir':'Selecionar';
    $('#savedLabSelectMode').setAttribute('aria-pressed',String(selectingLabs));
    $('#savedLabSelectActions').hidden=!selectingLabs;$('#savedLabSelectionFooter').hidden=!selectingLabs;
    document.querySelector('.device-list').classList.toggle('selecting-saved-labs',selectingLabs);
    renderLabs();
  });
  $('#savedLabSelectAll').addEventListener('click',()=>{if(labOperationBusy)return;for(const lab of state.labs.filter(labMatches))selectedLabs.add(lab.id);renderLabs();});
  $('#savedLabClearSelection').addEventListener('click',()=>{if(labOperationBusy)return;selectedLabs.clear();renderLabs();});
  const stopDialog=$('#savedLabStopDialog');
  const closeStopDialog=()=>{if(!labOperationBusy){stopDialog.close();stopRequest=null;}};
  $('#savedLabStopClose').addEventListener('click',closeStopDialog);
  $('#savedLabStopCancel').addEventListener('click',closeStopDialog);
  stopDialog.addEventListener('cancel',event=>{if(labOperationBusy)event.preventDefault();else stopRequest=null;});
  $('#savedLabStopSelected').addEventListener('click',()=>{
    if(labOperationBusy||!selectedLabs.size)return;
    stopRequest={ids:[...selectedLabs],current:state.current};
    $('#savedLabStopSummary').textContent=`${stopRequest.ids.length} lab(s) selecionado(s). O HuntMob verificará o Android principal e os aparelhos adicionais desses labs. Apenas os que estiverem ligados serão desligados.`;
    $('#savedLabStopError').hidden=true;stopDialog.showModal();
  });
  $('#savedLabStopConfirm').addEventListener('click',async()=>{
    if(labOperationBusy||!stopRequest)return;
    if(stopRequest.current!==state.current){$('#savedLabStopError').textContent='O lab atual mudou. Atualize a lista.';$('#savedLabStopError').hidden=false;return;}
    labOperationBusy=true;updateLabSelection();$('#savedLabStopConfirm').disabled=true;$('#savedLabStopConfirm').textContent='Desligando…';$('#savedLabStopCancel').disabled=true;stopDialog.setAttribute('aria-busy','true');
    try{
      const request=stopRequest;
      const result=await authorizedPost('/api/device/action',{action:'stop-saved-labs',lab_ids:request.ids,expected_current_id:request.current});
      stopDialog.close();stopRequest=null;selectedLabs.clear();
      for(const item of result.results||[])if(item.state==='failed')selectedLabs.add(item.lab_id);
      if(devicePlatform==='android'&&result.results?.some(item=>item.lab_id===request.current&&item.state==='stopped'))stopDeviceScreen();
      await loadRuntime();await Promise.all([loadSavedLabs(),loadWorkspaceDevices()]);
      $('#savedLabSelectionStatus').textContent=result.failed
        ?`${result.stopped} desligado(s), ${result.inactive} inativo(s), ${result.failed} pendente(s). Confira os selecionados.`
        :`${result.stopped} desligado(s), ${result.inactive} já inativo(s). Dados preservados.`;
      notify(result.failed?'Alguns aparelhos não desligaram; confira os labs selecionados.':result.stopped?'Aparelhos desligados. Os labs continuam salvos em disco.':'Aparelhos já desligados. Para remover os labs e liberar espaço, use Excluir.');
    }catch(error){$('#savedLabStopError').textContent=error.message;$('#savedLabStopError').hidden=false;}
    finally{labOperationBusy=false;$('#savedLabStopConfirm').disabled=false;$('#savedLabStopConfirm').textContent='Desligar aparelhos ligados';$('#savedLabStopCancel').disabled=false;stopDialog.removeAttribute('aria-busy');updateLabSelection();}
  });
  const deleteDialog=$('#savedLabDeleteDialog');let deleteRequest;
  const closeDeleteDialog=()=>{if(!labOperationBusy){deleteDialog.close();deleteRequest=undefined;}};
  $('#savedLabDeleteClose').addEventListener('click',closeDeleteDialog);
  $('#savedLabDeleteCancel').addEventListener('click',closeDeleteDialog);
  deleteDialog.addEventListener('cancel',event=>{if(labOperationBusy)event.preventDefault();else deleteRequest=undefined;});
  $('#savedLabDeleteApproval').addEventListener('change',()=>{$('#savedLabDeleteConfirm').disabled=labOperationBusy||!$('#savedLabDeleteApproval').checked;});
  $('#savedLabDeleteSelected').addEventListener('click',()=>{
    if(labOperationBusy||!selectedLabs.size)return;
    deleteRequest={ids:[...selectedLabs],current:state.current};
    $('#savedLabDeleteSummary').textContent=`${deleteRequest.ids.length} lab(s) serão removidos da lista e do armazenamento deste worker.`;
    const list=$('#savedLabDeleteList');list.replaceChildren();
    for(const lab of state.labs.filter(item=>selectedLabs.has(item.id)))list.append(label('li','',`${labTitle(lab)} · API ${lab.android_api||35} · ${shortId(lab.id)}`));
    $('#savedLabDeleteApproval').checked=false;$('#savedLabDeleteConfirm').disabled=true;$('#savedLabDeleteError').hidden=true;
    deleteDialog.showModal();
  });
  $('#savedLabDeleteConfirm').addEventListener('click',async()=>{
    if(labOperationBusy||!deleteRequest||!$('#savedLabDeleteApproval').checked)return;
    if(deleteRequest.current!==state.current){$('#savedLabDeleteError').textContent='O lab atual mudou. Feche esta janela e selecione novamente.';$('#savedLabDeleteError').hidden=false;return;}
    labOperationBusy=true;updateLabSelection();$('#savedLabDeleteConfirm').disabled=true;$('#savedLabDeleteConfirm').textContent='Excluindo…';$('#savedLabDeleteCancel').disabled=true;$('#savedLabDeleteApproval').disabled=true;deleteDialog.setAttribute('aria-busy','true');
    try{
      const request=deleteRequest;
      const result=await authorizedPost('/api/device/action',{action:'delete-saved-labs',lab_ids:request.ids,expected_current_id:request.current,delete_data:true});
      deleteDialog.close();deleteRequest=undefined;selectedLabs.clear();
      for(const item of result.results||[])if(item.state==='failed')selectedLabs.add(item.lab_id);
      if(devicePlatform==='android'&&result.results?.some(item=>item.lab_id===request.current&&item.state==='deleted'))stopDeviceScreen();
      await loadRuntime();await Promise.all([loadSavedLabs(),loadWorkspaceDevices()]);
      notify(result.failed?`${result.deleted} lab(s) excluído(s); ${result.failed} pendente(s). Os pendentes continuam selecionados.`:`${result.deleted} lab(s) excluído(s). Apps e dados removidos.`);
    }catch(error){$('#savedLabDeleteError').textContent=error.message;$('#savedLabDeleteError').hidden=false;}
    finally{labOperationBusy=false;$('#savedLabDeleteConfirm').disabled=!$('#savedLabDeleteApproval').checked;$('#savedLabDeleteConfirm').textContent='Excluir definitivamente';$('#savedLabDeleteCancel').disabled=false;$('#savedLabDeleteApproval').disabled=false;deleteDialog.removeAttribute('aria-busy');updateLabSelection();}
  });
  $('#sidebarNewLab').addEventListener('click',()=>{$('#newLab').click();closeDrawer();});
  for(const id of ['runtimeDevice','iosDevice'])$('#'+id).addEventListener('click',closeDrawer);
  $('#runtimeDevice').addEventListener('click',async()=>{if(state.android?.devices?.[0]?.state==='on')return;try{await deviceAction('start');await loadRuntime();await loadWorkspaceDevices();}catch(error){notify(error.message);}});
})();
