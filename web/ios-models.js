// Compatibility uses the local CoreSimulator device ranges, not a cosmetic phone name.
(() => {
  const legacyNames=new Set(['iPhone 7','iPhone 7 Plus','iPhone 8','iPhone 8 Plus','iPhone X']);
  function version(id){const m=String(id||'').match(/iOS-(\d+)-(\d+)(?:-(\d+))?$/);return m?Number(m[1])*65536+Number(m[2])*256+Number(m[3]||0):null;}
  function compatible(model,runtime){const value=version(runtime);return value!==null&&value>=model.minimum&&value<=model.maximum;}
  function range(model){const low=Math.floor(model.minimum/65536),high=Math.floor(model.maximum/65536);return high>100?`iOS ${low}+`:`iOS ${low}–${high}`;}
  function label(model,encoded){return model.name+(encoded<model.minimum||encoded>model.maximum?' · '+range(model):'');}
  function render(container,catalog){if(!container)return;const wasOpen=container.querySelector('details')?.open;container.replaceChildren();
    const models=(catalog?.models||[]).filter(model=>legacyNames.has(model.name));if(!models.length)return;
    const details=document.createElement('details');details.className='legacy-iphone-models';details.open=!!wasOpen;
    const summary=document.createElement('summary');summary.textContent='iPhone 7, 8 e X · compatibilidade';details.append(summary);
    const intro=document.createElement('p');intro.textContent='O modelo existe no catálogo Apple, mas precisa de um runtime compatível para iniciar.';details.append(intro);
    const list=document.createElement('ul');
    for(const model of models){const item=document.createElement('li'),name=document.createElement('strong'),support=document.createElement('small'),state=document.createElement('span');name.textContent=model.name;support.textContent=range(model);const runtimes=(catalog.runtimes||[]).filter(runtime=>compatible(model,runtime.id));state.textContent=runtimes.length?'Disponível com '+runtimes.map(r=>r.name).join(', '):'Sem runtime compatível neste worker';state.dataset.available=String(!!runtimes.length);item.append(name,support,state);list.append(item);}
    details.append(list);const note=document.createElement('p');note.textContent='iOS 26/27 não inicia esses modelos. Para iOS 15/16, é necessário um worker com macOS, Xcode e runtime compatíveis; um iPhone físico usa outro fluxo.';details.append(note);container.append(details);
  }
  window.huntmobIosModels={version,compatible,range,label,render};
})();
