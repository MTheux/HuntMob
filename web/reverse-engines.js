// REA evidence and Companion preparation share the selected APK identity.
let reaContext,reaPoll,reaReady=false,companionReady=false,modelReady=false,reaRunning=false,modelRunning=false,reaEvidenceAvailable=false;
const reaElements={run:document.querySelector('#runRea'),companion:document.querySelector('#prepareCompanion'),
  model:document.querySelector('#runLocalModel'),modelState:document.querySelector('#localModelState'),
  status:document.querySelector('#reverseEngineStatus'),download:document.querySelector('#downloadCompanion')};
function reaIdentity(){return reaContext&&{package_id:reaContext.package_id,workspace_id:reaContext.workspace_id,run_id:reaContext.run_id,sha256:reaContext.sha256};}
function reaCurrent(){return reaContext&&currentSelectedPackage===reaContext.package_id&&activeLab.id===reaContext.workspace_id&&reverseAnalysis?.run_id===reaContext.run_id;}
function reaQuery(){const i=reaIdentity();return new URLSearchParams({package:i.package_id,workspace:i.workspace_id,run:i.run_id,sha256:i.sha256});}
function reaButtons(){reaElements.run.disabled=!reaReady||!reaCurrent()||reaRunning||modelRunning;reaElements.companion.disabled=!companionReady||!reaCurrent()||!reaEvidenceAvailable||reaRunning||modelRunning;reaElements.model.disabled=!modelReady||!companionReady||!reaCurrent()||!reaEvidenceAvailable||reaRunning||modelRunning;document.querySelector('#refreshAgentReview').disabled=!reaCurrent();}
const reaOperationLabels={package:'Package e Manifest',classes:'Busca de classes',class:'Membros da classe',method:'Método decompilado',references:'Referências da classe'};
function reaElement(tag,className,textValue){const element=document.createElement(tag);if(className)element.className=className;if(textValue!==undefined)element.textContent=String(textValue);return element;}
function reaFact(container,label,value){const row=reaElement('div','rea-fact');row.append(reaElement('span','',label),reaElement('strong','',value));container.append(row);}
function reaNote(container,title,body){const row=reaElement('div','rea-note');row.append(reaElement('strong','',title),reaElement('p','',body));container.append(row);}
function reaManifestFacts(value){
  const xml=typeof value==='string'?value:typeof value?.text==='string'?value.text:'';
  if(!xml)return {exported:[],debuggable:null,backup:null};
  const parsed=new DOMParser().parseFromString(xml,'application/xml');
  if(parsed.querySelector('parsererror'))return {exported:[],debuggable:null,backup:null};
  const android='http://schemas.android.com/apk/res/android';
  const attribute=(node,name)=>node?.getAttributeNS(android,name)??node?.getAttribute(`android:${name}`);
  const app=parsed.querySelector('application');
  const exported=[...parsed.querySelectorAll('activity,service,receiver,provider')].filter(node=>attribute(node,'exported')==='true').map(node=>({kind:node.tagName,name:attribute(node,'name')||'sem nome'}));
  return {exported,debuggable:attribute(app,'debuggable'),backup:attribute(app,'allowBackup')};
}
function reaRenderResults(data){
  const completed=data.jobs.filter(job=>job.state==='complete'&&job.evidence);
  const panel=document.querySelector('#reaResultPanel');panel.hidden=!completed.length;
  const findings=document.querySelector('#reaFindings'),limits=document.querySelector('#reaLimits'),metrics=document.querySelector('#reaMetrics'),provenance=document.querySelector('#reaProvenance');
  findings.replaceChildren();limits.replaceChildren();metrics.replaceChildren();provenance.replaceChildren();
  const latest=completed[0];
  if(latest){
    const evidence=latest.evidence||{},result=evidence.normalized_result||{},manifest=reaManifestFacts(result.manifest);
    const packageResult=latest.operation==='package'&&typeof result.package_name==='string';
    document.querySelector('#reaResultTitle').textContent=packageResult?result.package_name:(reaOperationLabels[latest.operation]||'Inspeção REA');
    document.querySelector('#reaResultSubtitle').textContent=packageResult?`Versão ${result.version_name||'não informada'} · min API ${result.min_sdk||'—'} · target API ${result.target_sdk||'—'}`:`${reaOperationLabels[latest.operation]||latest.operation} · leitura estática do APK selecionado`;
    if(packageResult){
      const values=[['Classes',result.class_count],['Recursos',result.resource_count],['Permissões',Array.isArray(result.permissions)?result.permissions.length:null],['Exportados explícitos',manifest.exported.length]];
      values.forEach(([label,value])=>{const box=reaElement('div','rea-metric');box.append(reaElement('strong','',value??'—'),reaElement('span','',label));metrics.append(box);});
      const identity=reaElement('div','rea-fact-group');reaFact(identity,'Pacote',result.package_name);reaFact(identity,'SDK mínimo / alvo',`${result.min_sdk||'—'} / ${result.target_sdk||'—'}`);findings.append(identity);
      if(manifest.debuggable==='true')reaNote(findings,'Debuggable declarado','O Manifest declara android:debuggable=true. Confirme o impacto no build e no ambiente de teste.');
      if(manifest.backup==='true')reaNote(findings,'Backup permitido no Manifest','O Manifest declara android:allowBackup=true. A exposição de dados depende de versão, política e conteúdo do app.');
      if(manifest.exported.length){const group=reaElement('div','rea-list-group');group.append(reaElement('strong','','Componentes com exported=true'));const list=reaElement('ul');manifest.exported.forEach(item=>{const row=reaElement('li');row.append(reaElement('span','',item.kind),reaElement('code','',item.name));list.append(row);});group.append(list);findings.append(group);}
      if(Array.isArray(result.permissions)&&result.permissions.length){const group=reaElement('details','rea-permissions');group.append(reaElement('summary','',`${result.permissions.length} permissões declaradas`));const list=reaElement('ul');result.permissions.forEach(permission=>list.append(reaElement('li','',permission)));group.append(list);findings.append(group);}
      if(result.signature_verification==='not_performed')reaNote(limits,'Assinatura não verificada','Este provider não verificou a assinatura do APK.');
      reaNote(limits,'Exposição efetiva a confirmar','A contagem mostra apenas exported=true explícito. Defaults e intent filters dependem do componente e da versão Android.');
    }else{
      const entries=Object.entries(result).filter(([key])=>!['engine','manifest'].includes(key)).slice(0,8);
      entries.forEach(([key,value])=>reaFact(findings,key,typeof value==='string'?value.slice(0,500):JSON.stringify(value).slice(0,500)));
      if(!entries.length)reaNote(findings,'Evidência registrada','Abra o registro técnico para examinar o resultado desta operação.');
    }
    reaNote(limits,'Somente análise estática','O REA não executou o app, não testou o backend e não confirmou exploração ou vulnerabilidade.');
    reaNote(limits,'Avaliação separada','O Companion prepara contexto; o agente ou modelo local ainda precisa avaliar as evidências e a revisão humana decide o que investigar.');
    const evidenceId=evidence.evidence_id||'sem ID';
    const date=latest.created_at?new Date(latest.created_at):null;
    const when=date&&!Number.isNaN(date.valueOf())?date.toLocaleString('pt-BR'):'horário indisponível';
    provenance.append(reaElement('span','',`${evidence.provider?.name||'REA'} · ${when}`),reaElement('code','',`Evidence ${evidenceId}`),reaElement('code','',`SHA256 ${(latest.sha256||'').slice(0,16)}…`));
  }
  const evidenceList=document.querySelector('#reaEvidenceOutput');evidenceList.replaceChildren();
  data.jobs.forEach(job=>{const row=reaElement('div','rea-evidence-row');row.append(reaElement('strong','',reaOperationLabels[job.operation]||job.operation||'Inspeção'),reaElement('span',`rea-state-${job.state}`,job.state==='complete'?'Concluída':job.state==='running'?'Em andamento':'Não concluída'));const meta=reaElement('small','',job.state==='complete'?`Evidence ${job.evidence?.evidence_id||'sem ID'}`:job.reason||'Aguardando resultado');row.append(meta);evidenceList.append(row);});
  document.querySelector('#reaEvidenceRaw').textContent=JSON.stringify(data.jobs,null,2);
  const review=data.reviews?.[0],reviewPanel=document.querySelector('#agentReviewDetails'),reviewBody=document.querySelector('#agentReviewOutput');
  reviewPanel.hidden=!review;document.querySelector('#reaReviewEmpty').hidden=!!review;reviewBody.replaceChildren();
  if(review){
    reviewBody.append(reaElement('p','rea-review-summary',review.summary));
    const groups=[['Observações com evidência',review.observations||[]],['Inferências a verificar',review.inferences||[]],['Lacunas e desconhecidos',review.unknowns||[]]];
    groups.forEach(([title,items])=>{if(!items.length)return;const section=reaElement('section');section.append(reaElement('h5','',title));const list=reaElement('ul');items.forEach(item=>{const row=reaElement('li');row.append(reaElement('span','',typeof item==='string'?item:item.text||''));if(item.evidence_id)row.append(reaElement('code','',item.evidence_id));list.append(row);});section.append(list);reviewBody.append(section);});
    reviewBody.append(reaElement('small','',`${review.source||'agente'} · ${review.model||'sem modelo informado'} · revisão humana pendente · não verificado independentemente`));
  }
}
window.addEventListener('huntmob:reverse-reset',()=>{clearTimeout(reaPoll);reaContext=null;reaRunning=false;modelRunning=false;reaEvidenceAvailable=false;reaButtons();reaElements.download.hidden=true;document.querySelector('#reaEvidenceDetails').hidden=true;document.querySelector('#reaResultPanel').hidden=true;document.querySelector('#agentReviewDetails').hidden=true;document.querySelector('#reaReviewEmpty').hidden=false;reaElements.status.textContent='Prepare a decompilação do app selecionado para habilitar a análise.';});
async function loadReaJobs(){
  clearTimeout(reaPoll);if(!reaCurrent()){reaButtons();return;}
  const identity=JSON.stringify(reaIdentity());
  try{
    const response=await fetch('/api/reverse/inspections?'+reaQuery(),{cache:'no-store'});const data=await response.json();
    if(identity!==JSON.stringify(reaIdentity())||!reaCurrent())return;
    if(!response.ok)throw new Error(data.reason||'Contexto mudou; atualize o Reverse.');
    reaRunning=data.jobs.some(job=>job.state==='running');const completed=data.jobs.filter(job=>job.state==='complete');
    modelRunning=data.model_jobs?.some(job=>job.state==='running')||false;reaEvidenceAvailable=completed.length>0;
    reaButtons();
    const details=document.querySelector('#reaEvidenceDetails');details.hidden=!data.jobs.length;
    reaRenderResults(data);
    const latest=data.jobs[0];
    if(latest)reaElements.status.textContent=reaRunning?'REA inspecionando o APK no worker…':latest.state==='complete'?`Leitura estática concluída · ${completed.length} evidência(s). Veja o resumo abaixo; isso ainda não é um finding.`:latest.reason||'Execução não concluída.';
    const latestModel=data.model_jobs?.[0];
    if(latestModel)reaElements.modelState.textContent=modelRunning?'Modelo local avaliando evidências REA…':latestModel.state==='complete'?`Avaliação local concluída com ${latestModel.model}; leia e revise o resultado abaixo.`:latestModel.reason||'Avaliação local interrompida.';
    if(reaRunning||modelRunning)reaPoll=setTimeout(loadReaJobs,1500);
  }catch(error){reaRunning=false;modelRunning=false;reaButtons();reaElements.status.textContent=error.message;}
}
window.addEventListener('huntmob:reverse',event=>{
  clearTimeout(reaPoll);reaContext={...event.detail,workspace_id:activeLab.id};reaRunning=false;modelRunning=false;reaEvidenceAvailable=false;
  reaElements.download.hidden=true;document.querySelector('#reaEvidenceDetails').hidden=true;document.querySelector('#reaResultPanel').hidden=true;document.querySelector('#agentReviewDetails').hidden=true;
  reaElements.status.textContent='APK preparado. Escolha uma inspeção REA.';reaButtons();void loadReaJobs();
});
document.querySelector('#refreshAgentReview').addEventListener('click',loadReaJobs);
document.querySelector('#reaOperation').addEventListener('change',()=>{
  const operation=document.querySelector('#reaOperation').value;
  document.querySelector('#reaQueryField').hidden=operation!=='classes';
  document.querySelector('#reaClassField').hidden=!['class','method','references'].includes(operation);
  document.querySelector('#reaMethodField').hidden=operation!=='method';document.querySelector('#reaOverloadField').hidden=operation!=='method';
});
window.huntmobReaInspectPackage=async()=>{
  if(!reaReady)throw new Error('REA indisponível neste worker.');
  if(!reaCurrent())throw new Error('APK e decompilação não correspondem ao app selecionado.');
  if(reaRunning)throw new Error('Uma inspeção REA já está em andamento neste APK.');
  document.querySelector('#reaOperation').value='package';
  document.querySelector('#reaOperation').dispatchEvent(new Event('change'));
  reaRunning=true;reaButtons();reaElements.status.textContent='Iniciando inspeção REA de Package e Manifest…';
  try{
    const result=await authorizedPost('/api/reverse/inspect',{...reaIdentity(),operation:'package'});
    await loadReaJobs();
    return result;
  }catch(error){reaRunning=false;reaButtons();reaElements.status.textContent=error.message;throw error;}
};
reaElements.run.addEventListener('click',async()=>{
  if(!reaCurrent()||reaRunning)return;reaRunning=true;reaButtons();reaElements.download.hidden=true;
  reaElements.status.textContent='Iniciando inspeção REA…';
  const operation=document.querySelector('#reaOperation').value;
  const payload={...reaIdentity(),operation,query:document.querySelector('#reaQuery').value,class_name:document.querySelector('#reaClass').value,method_name:document.querySelector('#reaMethod').value};
  const overload=document.querySelector('#reaOverload').value;if(overload!=='')payload.overload_index=Number(overload);
  try{await authorizedPost('/api/reverse/inspect',payload);await loadReaJobs();}
  catch(error){reaRunning=false;reaButtons();reaElements.status.textContent=error.message;}
});
reaElements.companion.addEventListener('click',async()=>{
  if(!reaCurrent())return;reaElements.companion.disabled=true;
  try{
    const response=await fetch('/api/reverse/companion?'+reaQuery(),{cache:'no-store'});const data=await response.json();
    if(!response.ok)throw new Error(data.reason||'Contexto Companion indisponível.');
    if(!reaCurrent()||data.sha256!==reaContext.sha256)return;
    reaElements.download.href='/api/reverse/companion.zip?'+reaQuery();reaElements.download.hidden=false;
    reaElements.status.textContent='Contexto Companion preparado. Avaliação pelo agente pendente: conecte seu MCP em “Conectar agente” e solicite reverse_context, ou baixe o pacote. Nenhum modelo foi chamado automaticamente.';
  }catch(error){reaElements.status.textContent=error.message;}
  finally{reaButtons();}
});
reaElements.model.addEventListener('click',async()=>{
  if(!reaCurrent()||!reaEvidenceAvailable||modelRunning)return;
  modelRunning=true;reaButtons();reaElements.modelState.textContent='Iniciando avaliação no Ollama local…';
  try{await authorizedPost('/api/reverse/model-review',reaIdentity());await loadReaJobs();}
  catch(error){modelRunning=false;reaButtons();reaElements.modelState.textContent=error.message;}
});
fetch('/api/reverse/engines',{cache:'no-store'}).then(response=>response.json()).then(data=>{
  reaReady=data.rea_ready;companionReady=data.companion_ready;modelReady=data.model_connected;
  document.querySelector('#reverseProvidersState').textContent=reaReady&&companionReady?'Worker preparado':reaReady?'REA preparado':'Configuração necessária';
  reaElements.modelState.textContent=modelReady?`Modelo local conectado: ${data.model_name}. Avaliação exige ação explícita e permanece sujeita a revisão humana.`:'Modelo local indisponível; inicie Ollama e instale hermes3:8b.';
  if(!reaReady)reaElements.status.textContent=data.rea_reason;
  reaButtons();if(typeof reverseAnalysis!=='undefined'&&reverseAnalysis)window.dispatchEvent(new CustomEvent('huntmob:reverse',{detail:reverseAnalysis}));
}).catch(()=>{document.querySelector('#reverseProvidersState').textContent='Worker indisponível';});
