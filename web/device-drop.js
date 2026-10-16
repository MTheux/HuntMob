// Files are uploaded from this browser to the worker that owns the selected Android.
(() => {
  const viewport=document.querySelector('#deviceViewport');
  const overlay=document.querySelector('#deviceDropOverlay');
  const title=document.querySelector('#deviceDropTitle');
  const detail=document.querySelector('#deviceDropDetail');
  const picker=document.querySelector('#deviceFileInput');
  const choose=document.querySelector('#chooseDeviceFile');
  let busy=false,hideTimer;
  const hasFiles=event=>[...(event.dataTransfer?.types||[])].includes('Files');
  const visibleAndroid=id=>[...viewport.querySelectorAll('.device-tile')].find(tile=>tile.dataset.deviceId===id&&!tile.hidden);
  const targetAt=element=>element?.closest?.('.device-tile')?.dataset.deviceId || '';
  function show(heading,message,kind=''){
    clearTimeout(hideTimer);overlay.hidden=false;overlay.className='device-drop-overlay'+(kind?' drop-'+kind:'');title.textContent=heading;detail.textContent=message;
  }
  function hide(delay=0){clearTimeout(hideTimer);hideTimer=setTimeout(()=>{if(!busy)overlay.hidden=true;},delay);}
  async function send(file,id){
    if(busy)return;
    if(devicePlatform!=='android'||!activeLab.id||!visibleAndroid(id)){notify('Escolha um Android ligado no canvas.');return;}
    if(!file||!file.size||file.size>512*1024*1024){show('Arquivo recusado','Escolha um arquivo de até 512 MB.','error');hide(4000);return;}
    busy=true;choose.disabled=true;
    const apk=file.name.toLowerCase().endsWith('.apk');
    show(apk?'Instalando APK…':'Enviando arquivo…',`${file.name} · ${window.huntmobCanvas?.label(id)||'Android'}`);
    try{
      const response=await sessionFetch('/api/device/drop',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-HuntMob-Approved':'true','X-HuntMob-Workspace':activeLab.id,'X-HuntMob-Device':id,'X-HuntMob-Filename':encodeURIComponent(file.name)},body:file});
      const result=await response.json();
      if(!response.ok||!result.ok)throw new Error(result.reason||'Envio não concluído.');
      if(result.kind==='apk'){
        show(result.launched?'APK instalado e aberto':'APK instalado',result.launched?`${result.package_id} · mesmo Android`:`${result.package_id} · sem atividade inicial para abrir`,'done');
        if(id===activeLab.id){await loadRuntime();await loadInstalledApps();if(result.package_id)await selectApp(result.package_id);}
      }else show('Arquivo no Android',`${file.name} · Downloads/HuntMob`,'done');
      notify(apk?'APK instalado no Android escolhido':'Arquivo enviado ao Android escolhido');
      hide(5000);
    }catch(error){show('Envio não concluído',error.message,'error');notify(error.message);hide(6500);}
    finally{busy=false;choose.disabled=false;picker.value='';}
  }
  viewport.addEventListener('dragover',event=>{
    if(!hasFiles(event)||devicePlatform!=='android')return;
    event.preventDefault();event.dataTransfer.dropEffect='copy';
    if(busy)return;
    const id=targetAt(event.target);
    show(id&&visibleAndroid(id)?'Solte neste Android':'Solte sobre um aparelho',id?'APK instala e abre · outros arquivos vão para Downloads':'Arraste o arquivo até a tela do Android.');
  });
  viewport.addEventListener('dragleave',event=>{if(!viewport.contains(event.relatedTarget)&&!busy)hide(80);});
  viewport.addEventListener('drop',event=>{
    if(!hasFiles(event))return;
    event.preventDefault();
    const id=targetAt(event.target);
    const files=[...(event.dataTransfer?.files||[])];
    if(files.length!==1){show('Solte um arquivo por vez','Selecione um único arquivo para este Android.','error');hide(4000);return;}
    if(!id||!visibleAndroid(id)){show('Escolha um Android','Solte o arquivo dentro da tela do aparelho.','error');hide(4000);return;}
    void send(files[0],id);
  });
  document.addEventListener('dragover',event=>{
    if(hasFiles(event)&&!event.target.closest('input[type="file"]'))event.preventDefault();
  });
  document.addEventListener('drop',event=>{
    if(!hasFiles(event)||viewport.contains(event.target)||event.target.closest('input[type="file"]'))return;
    event.preventDefault();
    show('Escolha um Android','Solte o arquivo dentro da tela do aparelho.','error');hide(4000);
  });
  choose.addEventListener('click',()=>picker.click());
  picker.addEventListener('change',()=>{if(picker.files?.[0])void send(picker.files[0],activeLab.id);});
})();
