// Capabilities implemented by HuntMob, independent of whether a device is online.
(function(root){
  const tabs={files:{state:'android',reason:'Sandbox iOS ainda não integrado.'},dast:{state:'android',reason:'DAST automatizado disponível no Android.'},frida:{state:'experimental',reason:'Sonda nativa Simmy; conexão depende do runtime e do app.'}};
  const androidControls={root:'Root / jailbreak: indisponível no Apple Simulator.',camera:'Webcam do app: integrada ao Android Emulator.',network:'Rádios e velocidade de rede: controles do Android.',sensor:'Sensores virtuais: controles do Android.'};
  function tab(name,ios){return ios?(tabs[name]||{state:'supported'}):{state:'supported'};}
  function control(button,ios){
    if(!ios)return {state:'supported'};
    const key=button.id==='quickRoot'?'root':button.dataset.panel==='camera'?'camera':button.dataset.controlPanel;
    return androidControls[key]?{state:'android',reason:androidControls[key]}:button.dataset.toolShortcut==='frida'?tabs.frida:{state:'supported'};
  }
  function appRoot(state,stock){
    if(!state)return {disabled:true,reason:'Consultando Magisk neste Android…'};
    if(state.enabled)return {disabled:false,reason:'Magisk ativo no mesmo AVD. Cada app pede autorização individual ao Magisk. Clique para desativar.'};
    if(state.available)return {disabled:false,reason:'Ativa Magisk temporário neste mesmo AVD. O Android reinicia seus processos e cada app pede autorização individual.'};
    return {disabled:true,reason:stock?'Google Play sem root: esta imagem não oferece ADB root nem Magisk temporário. DAST neste perfil requer Frida Gadget integrado ao build de teste.':'Esta imagem não oferece Magisk temporário. A disponibilidade de ADB root para o servidor Frida é verificada separadamente.'};
  }
  const api={tab,control,androidControls,appRoot};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.huntmobToolSupport=api;
})(typeof window==='undefined'?this:window);
