// Block API initialization until the local operator is authenticated. The
// bootstrap fragment is removed before any other script or network request.
(function(){
  const nativeFetch=window.fetch.bind(window);
  const fragment=new URLSearchParams(location.hash.slice(1));
  let launchToken=fragment.get('operator');
  if(launchToken)history.replaceState(null,'',location.pathname+location.search);
  let pending;
  let disabled=false;
  let blockedError;
  let proof=sessionStorage.getItem('huntmob.operatorProof')||'';
  const operatorRequired=()=>new Error('Sessão de operador indisponível. Abra o link seguro gerado pelo launcher.');
  async function bootstrap(token){
    const response=await nativeFetch('/api/auth/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),cache:'no-store'});
    if(!response.ok)throw new Error('Endereço privado inválido ou expirado. Use o arquivo gerado pelo launcher atual.');
    proof=(await response.json()).proof;sessionStorage.setItem('huntmob.operatorProof',proof);
  }
  function connect(){
    if(pending)return pending;
    pending=(async()=>{
      try{
        if(launchToken){const token=launchToken;launchToken=null;await bootstrap(token);blockedError=undefined;return true;}
        const response=await nativeFetch('/api/auth/status',{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});
        if(response.ok){const data=await response.json();if(data.operator===false){disabled=true;blockedError=undefined;return true;}if(data.authenticated){blockedError=undefined;return true;}}
        blockedError=operatorRequired();return false;
      }catch(error){blockedError=error;return false;}
    })().finally(()=>{pending=undefined;});
    return pending;
  }
  const initial=connect();
  window.fetch=async(input,options)=>{
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    const protectedApi=url.origin===location.origin&&url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/api/auth/')&&url.pathname!=='/api/client/ping';
    if(!protectedApi)return nativeFetch(input,options);
    if(!await initial)throw blockedError||operatorRequired();
    if(disabled)return nativeFetch(input,options);
    const send=()=>{const headers=new Headers(options?.headers||(input instanceof Request?input.headers:{}));headers.set('X-HuntMob-Operator',proof);return nativeFetch(input,{...options,headers});};
    let response=await send();
    if(response.status===401){if(!await connect())throw blockedError||operatorRequired();response=await send();}
    return response;
  };
  async function mediaUrl(path){
    if(!await initial)throw blockedError||operatorRequired();
    if(disabled)return new URL(path,location.origin).href;
    let response=await nativeFetch('/api/auth/ticket?'+new URLSearchParams({path}),{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});
    if(response.status===401){if(!await connect())throw blockedError||operatorRequired();response=await nativeFetch('/api/auth/ticket?'+new URLSearchParams({path}),{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});}
    if(!response.ok)throw new Error('Não foi possível autorizar este download.');
    const data=await response.json(),url=new URL(path,location.origin);url.searchParams.set('_operator_ticket',data.ticket);return url.href;
  }
  window.huntmobOperator={mediaUrl};
  document.addEventListener('click',async event=>{
    const link=event.target.closest('a[href]');if(!link)return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/api/')||url.searchParams.has('_operator_ticket'))return;
    event.preventDefault();event.stopImmediatePropagation();
    try{const target=await mediaUrl(url.pathname+url.search);if(link.target==='_blank')window.open(target,'_blank','noopener,noreferrer');else{const download=document.createElement('a');download.href=target;download.download=link.download;download.rel='noreferrer';download.addEventListener('click',e=>e.stopPropagation());document.body.append(download);download.click();download.remove();}}
    catch(error){console.error(error);}
  },true);
})();
