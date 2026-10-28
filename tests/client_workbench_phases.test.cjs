const {test}=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
// workbench-phases.js é dual CJS/browser: require no mesmo realm (evita arrays
// cross-realm) e expõe PHASE_TABS/tabsForPhase/phaseForTab.
function load(){delete require.cache[require.resolve('../web/workbench-phases.js')];return require('../web/workbench-phases.js');}

test('tabsForPhase devolve as abas da fase na ordem do mapa',()=>{
 const {tabsForPhase}=load();
 assert.deepEqual(tabsForPhase('dinamico'),['dast','frida','proxy']);
 assert.deepEqual(tabsForPhase('engagement'),['device-tools','files']);
});
test('phaseForTab devolve a fase dona de cada aba',()=>{
 const {phaseForTab}=load();
 assert.equal(phaseForTab('proxy'),'dinamico');
 assert.equal(phaseForTab('reverse'),'estatico');
 assert.equal(phaseForTab('evidence'),'evidencias');
});
test('phaseForTab cai em engagement para aba desconhecida',()=>{
 const {phaseForTab}=load();
 assert.equal(phaseForTab('inexistente'),'engagement');
});
test('as 7 abas atuais aparecem exatamente uma vez somando todas as fases',()=>{
 const {PHASE_TABS}=load();
 const all=Object.values(PHASE_TABS).flat();
 assert.equal(all.length,7);
 assert.deepEqual([...all].sort(),['dast','device-tools','evidence','files','frida','proxy','reverse']);
});

// --- revealPhase: document stub mínimo ---
function classList(init){const s=new Set(init);return{add:x=>s.add(x),remove:x=>s.delete(x),toggle:(x,on)=>{if(on)s.add(x);else s.delete(x);},contains:x=>s.has(x)};}
function makeDoc(hidden=[]){
 const tabs=['device-tools','files','reverse','dast','frida','proxy','evidence'];
 const phases=['engagement','estatico','dinamico','evidencias'].map(p=>({dataset:{phase:p},classList:classList(),setAttribute(){}}));
 const nav={},panel={};
 tabs.forEach(id=>{nav[id]={dataset:{tab:id},hidden:hidden.includes(id),disabled:false};panel[id]={id:'tab-'+id,classList:classList()};});
 return {phases,panel,
  querySelectorAll(sel){if(sel==='.phase-spine .phase')return phases;if(sel==='.tab-content')return tabs.map(id=>panel[id]);return[];},
  querySelector(sel){let m;if((m=sel.match(/^\[data-tab="(.+)"\]$/)))return nav[m[1]]||null;if((m=sel.match(/^#tab-(.+)$/)))return panel[m[1]]||null;return null;}};
}
test('revealPhase revela o conjunto de abas da fase e marca a fase ativa',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase('dinamico',doc),['dast','frida','proxy']);
 assert.ok(doc.panel['dast'].classList.contains('active'));
 assert.ok(doc.panel['proxy'].classList.contains('active'));
 assert.ok(!doc.panel['device-tools'].classList.contains('active'));
 assert.ok(doc.phases.find(p=>p.dataset.phase==='dinamico').classList.contains('active'));
});
test('revealPhase devolve [] quando todas as abas da fase estao indisponiveis',()=>{
 const {revealPhase}=load();const doc=makeDoc(['reverse']);
 assert.deepEqual(revealPhase('estatico',doc),[]);
 assert.ok(!doc.panel['reverse'].classList.contains('active'));
});
test('preferencia invalida restaura a fase engagement',()=>{
 const {revealPhase,phaseForTab}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase(phaseForTab('xxx'),doc),['device-tools','files']);
});
