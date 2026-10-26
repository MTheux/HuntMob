// Block API initialization until the local operator is authenticated. The
// bootstrap fragment is removed before any other script or network request.
(function(){
  const nativeFetch=window.fetch.bind(window);
  const fragment=new URLSearchParams(location.hash.slice(1));
  let launchToken=fragment.get('operator');
  if(launchToken)history.replaceState(null,'',location.pathname+location.search);
  let pending;
  let disabled=false;
  let proof=sessionStorage.getItem('huntmob.operatorProof')||'';
  const dialog=document.createElement('dialog');dialog.id='operatorSessionDialog';
  const shell=document.createElement('form');shell.className='dialog-shell';
  const heading=document.createElement('h2');heading.textContent='Conectar ao HuntMob';
  const description=document.createElement('p');description.className='privacy-note';description.textContent='Abra o endereço privado gerado pelo launcher em ~/.huntmob/operator-access-url.txt, ou cole esse endereço abaixo.';
  const input=document.createElement('input');input.type='password';input.autocomplete='off';input.required=true;input.setAttribute('aria-label','Endereço privado do operador');
  const button=document.createElement('button');button.type='submit';button.className='primary';button.textContent='Conectar sessão local';
  const status=document.createElement('p');status.setAttribute('role','status');status.className='privacy-note';
  shell.append(heading,description,input,button,status);dialog.append(shell);document.body.append(dialog);
  dialog.addEventListener('cancel',event=>event.preventDefault());
  async function bootstrap(token){
    const response=await nativeFetch('/api/auth/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),cache:'no-store'});
    if(!response.ok)throw new Error('Endereço privado inválido ou expirado. Use o arquivo gerado pelo launcher atual.');
    proof=(await response.json()).proof;sessionStorage.setItem('huntmob.operatorProof',proof);
  }
  function connect(){
    if(pending)return pending;
    pending=(async()=>{
      try{
        if(launchToken){const token=launchToken;launchToken=null;await bootstrap(token);return;}
        const response=await nativeFetch('/api/auth/status',{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});
        if(response.ok){const data=await response.json();if(data.operator===false){disabled=true;return;}if(data.authenticated)return;}
      }catch(error){status.textContent=error.message;}
      dialog.showModal();
      await new Promise(resolve=>{
        shell.onsubmit=async event=>{
          event.preventDefault();button.disabled=true;
          try{
            let token=input.value.trim();
            if(token.includes('#'))token=new URLSearchParams(new URL(token).hash.slice(1)).get('operator')||'';
            await bootstrap(token);input.value='';shell.onsubmit=null;dialog.close();resolve();
          }catch(error){status.textContent=error.message;}
          finally{button.disabled=false;}
        };
      });
    })().finally(()=>{pending=undefined;});
    return pending;
  }
  const initial=connect();
  window.fetch=async(input,options)=>{
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    const protectedApi=url.origin===location.origin&&url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/api/auth/')&&url.pathname!=='/api/client/ping';
    if(!protectedApi)return nativeFetch(input,options);
    await initial;
    if(disabled)return nativeFetch(input,options);
    const send=()=>{const headers=new Headers(options?.headers||(input instanceof Request?input.headers:{}));headers.set('X-HuntMob-Operator',proof);return nativeFetch(input,{...options,headers});};
    let response=await send();
    if(response.status===401){await connect();response=await send();}
    return response;
  };
  async function mediaUrl(path){
    await initial;
    if(disabled)return new URL(path,location.origin).href;
    let response=await nativeFetch('/api/auth/ticket?'+new URLSearchParams({path}),{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});
    if(response.status===401){await connect();response=await nativeFetch('/api/auth/ticket?'+new URLSearchParams({path}),{cache:'no-store',headers:{'X-HuntMob-Operator':proof}});}
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
    catch(error){status.textContent=error.message;}
  },true);
})();
