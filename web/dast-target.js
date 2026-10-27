// Target selection only; starting instrumentation remains a separate user action.
(function(root, factory) {
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.huntmobDastTarget=api;
})(typeof globalThis!=='undefined'?globalThis:this, function() {
  const valid=value=>typeof value==='string'&&/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(value);
  function create({context,list,bind,onChange}) {
    let scope,epoch=0,apps=[],loaded=false,attempted=false,loading=false,binding='',error='';
    function state() {
      const ctx=context(),key=JSON.stringify([ctx.labId,!!ctx.available]);
      if(key!==scope){scope=key;epoch++;apps=[];loaded=attempted=loading=false;binding='';error='';}
      const locked=!!ctx.busy||!!ctx.active;
      return {...ctx,scope,apps:[...apps],loaded,attempted,loading,binding,error,
        disabled:!ctx.available||locked||loading||!!binding||!apps.length,
        // Inventory is read-only and remains available while instrumentation runs.
        refreshDisabled:!ctx.available||!!ctx.busy||loading||!!binding,
        browseOnly:!!ctx.available&&!!ctx.active&&!ctx.busy&&!loading&&!binding&&(!!apps.length||!!ctx.packageId),
        canStart:!!ctx.available&&!locked&&!loading&&!binding&&loaded&&apps.includes(ctx.packageId)&&!!ctx.sha256&&ctx.connectionReady===true};
    }
    function sync(){const view=state();onChange(view);return view;}
    function current(token){state();return token===epoch;}
    async function load() {
      const view=sync();if(view.refreshDisabled)return false;
      const token=++epoch;loading=true;attempted=true;error='';sync();
      try {
        const values=await list();if(!current(token))return false;
        apps=[...new Set(values.filter(valid))].sort();loaded=true;
        return true;
      } catch(failure) {
        if(current(token)){apps=[];loaded=false;error=failure.message||'Não foi possível listar os apps.';}
        return false;
      } finally {if(current(token)){loading=false;sync();}}
    }
    async function choose(packageId) {
      const view=sync();
      if(view.disabled||!valid(packageId)||!apps.includes(packageId))return false;
      if(view.packageId&&view.packageId!==packageId){error='Este laboratório já tem um app vinculado. Crie outro lab para selecionar um app diferente.';sync();return false;}
      const token=++epoch;binding=packageId;error='';sync();
      try {
        const result=await bind(packageId);if(!current(token))return false;
        if(result===false)throw new Error('O app não pôde ser vinculado. Atualize a lista e tente novamente.');
        return true;
      } catch(failure) {
        if(current(token))error=failure.message||'Não foi possível selecionar o app.';
        return false;
      } finally {if(current(token)){binding='';sync();}}
    }
    return {state,sync,load,choose};
  }
  return {create};
});
