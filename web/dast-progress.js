// Session time is measurable; coverage and report completion have no honest ETA.
(function(root, factory) {
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.huntmobDastProgress=api;
})(typeof globalThis!=='undefined'?globalThis:this, function() {
  const DEFAULT_COLLECTION_SECONDS=30*60;
  const seconds=value=>typeof value==='number'&&Number.isFinite(value)&&value>0?value:null;
  function timestamp(epoch,iso){return seconds(epoch)??(typeof iso==='string'&&Number.isFinite(Date.parse(iso))?Date.parse(iso)/1000:null);}
  function duration(value) {
    if(value===null||!Number.isFinite(value))return '—';
    const total=Math.max(0,Math.floor(value)),minutes=Math.floor(total/60);
    return `${String(minutes).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
  }
  function present({snapshot={},report,operation,error,now=Date.now()/1000}={}) {
    const receipt=snapshot.receipt||{},state=snapshot.state||'idle';
    const active=['running','starting'].includes(state),started=timestamp(receipt.started_epoch,receipt.started_at),ended=timestamp(receipt.ended_epoch,receipt.ended_at);
    const elapsed=started!==null&&(active||ended!==null)?Math.max(0,Math.floor((ended??now)-started)):null;
    const limit=seconds(receipt.max_session_seconds)??seconds(snapshot.limits?.max_session_seconds)??DEFAULT_COLLECTION_SECONDS;
    const remaining=elapsed===null?null:Math.max(0,Math.ceil(limit-elapsed));
    const percentage=elapsed===null?0:Math.min(100,Math.floor(elapsed/limit*100));
    const hasReport=!!receipt.id&&report?.job_id===receipt.id&&report?.lab_id===receipt.lab_id;
    const view={kind:'idle',title:'Aguardando início',value:0,indeterminate:false,percentage:'',
      timeLabel:'Tempo de coleta',time:duration(elapsed),remainingLabel:'Janela de coleta',remaining:duration(limit),
      detail:'A sessão é interativa. Inicie, exercite os fluxos do app e encerre para analisar.',steps:['pending','pending','pending'],hasReport};
    if(error)return {...view,kind:'error',title:'Não foi possível atualizar a sessão',detail:error,value:null};
    if(operation){
      const action=operation.action,analyzing=['stop','analyze'].includes(action);
      const titles={start:'Conectando observadores…',prepare:'Preparando Frida…',stop:'Encerrando e analisando…',analyze:'Analisando evidências…',capture:'Capturando evidência…'};
      return {...view,kind:'working',title:titles[action]||'Executando…',value:null,indeterminate:true,
        timeLabel:'Tempo nesta etapa',time:duration(Math.max(0,now-operation.started)),remainingLabel:'Previsão de conclusão',remaining:'Sem estimativa',
        detail:analyzing?'Consolidando os registros e gerando o relatório. Aguarde a confirmação de conclusão.':'Aguardando confirmação do worker. A coleta e a análise só avançam após a resposta.',
        steps:analyzing?['done',action==='stop'&&active?'current':'done',action==='stop'&&active?'pending':'current']:action==='capture'?['done','current','pending']:['current','pending','pending']};
    }
    if(state==='starting')return {...view,kind:'working',title:'Conectando observadores…',value:null,indeterminate:true,remainingLabel:'Previsão de conclusão',remaining:'Sem estimativa',detail:'Preparando a conexão e aguardando os observadores do app.',steps:['current','pending','pending']};
    if(state==='running'){
      const exhausted=remaining===0||Number(receipt.dropped_event_count)>0;
      return {...view,kind:exhausted?'limit':'collecting',title:exhausted?'Limite de coleta atingido':'Coletando evidências',value:percentage,
        percentage:`${percentage}% da janela de tempo`,remainingLabel:'Até o limite de tempo',remaining:duration(remaining),
        detail:exhausted?'O runtime deixou de registrar novos eventos por limite de tempo ou volume. Clique em Encerrar e analisar.':hasReport?'Relatório parcial atualizado. A coleta continua até você encerrar; o percentual indica tempo, sem medir cobertura.':`Janela de coleta de ${duration(limit)}; você pode encerrar antes. O percentual indica tempo decorrido, sem medir a cobertura dos testes.`,
        steps:['done','current',hasReport?'partial':'pending']};
    }
    if(hasReport)return {...view,kind:'complete',title:'Análise concluída',value:100,percentage:'Relatório pronto',remainingLabel:'Situação da coleta',remaining:'Encerrada',detail:'Relatório gerado para esta sessão. Achados e cobertura continuam sujeitos à revisão.',steps:['done','done','done']};
    if(['stopped','failed','detached','interrupted'].includes(state)){
      const normal=state==='stopped';
      return {...view,kind:normal?'stopped':'error',title:normal?'Coleta encerrada · análise pendente':'Sessão interrompida',value:0,remainingLabel:'Situação da coleta',remaining:'Encerrada',detail:normal?'Clique em Analisar evidências para gerar o relatório desta sessão.':'Confira o estado da sessão. As evidências já registradas podem ser analisadas.',steps:['done',normal?'done':'error','pending']};
    }
    return view;
  }
  function actions({active=false,busy=false,available=false,identified=false,canStart=false,hasReceipt=false}={}) {
    return {
      showStart:!active,startEnabled:available&&identified&&!busy&&canStart,showStop:active,stopEnabled:active&&!busy,
      captureEnabled:available&&identified&&!busy,analyzeEnabled:hasReceipt&&!busy,exportEnabled:hasReceipt&&!busy,
      analyzeLabel:active?'Gerar análise parcial':'Analisar evidências',
      help:busy?'Aguarde a operação em andamento.':active?'Sessão ativa: gere uma análise parcial para consultar resultados durante a coleta, ou use Encerrar e analisar para finalizar.':hasReceipt?'A coleta foi encerrada. Você pode analisar as evidências e exportar a sessão.':canStart?'Pronto para iniciar a coleta neste aparelho.':'Selecione o app e verifique a conexão Frida para iniciar.',
    };
  }
  return {present,duration,actions,DEFAULT_COLLECTION_SECONDS};
});
