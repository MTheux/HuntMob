let runtimeCatalog,iosRuntimeLoading=false;
async function fetchIosRuntimeCatalog(){
  const response=await fetch('/api/ios/runtime-catalog',{cache:'no-store',signal:AbortSignal.timeout(15000)});
  const data=await response.json();if(!response.ok||!data.ok)throw new Error('Catálogo iOS indisponível.');runtimeCatalog=data;return data;
}
function appendMissingIosVersions(select,data){
  for(const item of data.versions){if(item.state==='installed')continue;const option=new Option(item.name+' · '+(item.state==='other-worker'?'outro worker necessário':'não instalado'),'missing-'+item.version);option.disabled=true;select.add(option);}
}
function renderIosRuntimeCatalog(){
  if(!runtimeCatalog)return;
  document.querySelector('#iosRuntimesHost').textContent=`${runtimeCatalog.xcode||'Worker sem Xcode compatível'} · ${(runtimeCatalog.free_bytes/1e9).toFixed(1)} GB livres. Oferta Apple verificada em ${runtimeCatalog.catalog_observed_at}.`;
  document.querySelector('#iosRuntimesJob').textContent=runtimeCatalog.job?.reason||'Selecione Preparar em uma versão disponível para instalação.';
  const list=document.querySelector('#iosRuntimesList');list.replaceChildren();
  const filter=document.querySelector('#iosRuntimesSearch').value.trim().toLowerCase();
  const labels={installed:'Instalado','disk-space':'Falta espaço','other-worker':'Outro worker',historical:'Histórico · não validado',offered:'Disponível para preparar'};
  for(const item of runtimeCatalog.versions){
    if(filter&&!item.name.toLowerCase().includes(filter))continue;
    const row=document.createElement('article');row.className='ios-runtime-row';
    const content=document.createElement('div'),title=document.createElement('strong'),state=document.createElement('span'),reason=document.createElement('small');
    title.textContent=item.name;state.textContent=labels[item.state];state.dataset.state=item.state;reason.textContent=item.reason;
    content.append(title,state,reason);row.append(content);
    if(item.download_gb&&item.state!=='installed'){
      const button=document.createElement('button');button.type='button';button.className='outline';button.textContent='Preparar · '+item.download_gb.toFixed(2)+' GB';button.disabled=!item.can_install||runtimeCatalog.job?.state==='installing';button.title=item.reason;
      button.addEventListener('click',async()=>{button.disabled=true;try{await authorizedPost('/api/ios/action',{action:'install-runtime',version:item.version});await refreshIosRuntimes();}catch(error){document.querySelector('#iosRuntimesJob').textContent=error.message;}});row.append(button);
    }
    list.append(row);
  }
}
async function refreshIosRuntimes(){if(iosRuntimeLoading)return;iosRuntimeLoading=true;try{await fetchIosRuntimeCatalog();renderIosRuntimeCatalog();}catch(error){document.querySelector('#iosRuntimesJob').textContent=error.message;}finally{iosRuntimeLoading=false;}}
function openIosRuntimes(){document.querySelector('#iosRuntimesDialog').showModal();void refreshIosRuntimes();}
for(const id of ['manageLabIosVersions','manageWorkspaceIosVersions'])document.querySelector('#'+id).addEventListener('click',openIosRuntimes);
document.querySelector('#refreshIosRuntimes').addEventListener('click',refreshIosRuntimes);
document.querySelector('#iosRuntimesSearch').addEventListener('input',renderIosRuntimeCatalog);
window.setInterval(()=>{if(document.querySelector('#iosRuntimesDialog').open)refreshIosRuntimes();},5000);
