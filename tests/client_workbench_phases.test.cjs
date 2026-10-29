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
 assert.equal(phaseForTab('files'),'engagement');
});
test('phaseForTab cai em engagement para aba desconhecida',()=>{
 const {phaseForTab}=load();
 assert.equal(phaseForTab('inexistente'),'engagement');
});
test('as 6 abas atuais aparecem exatamente uma vez somando todas as fases',()=>{
 const {PHASE_TABS}=load();
 const all=Object.values(PHASE_TABS).flat();
 assert.equal(all.length,6);
 assert.deepEqual([...all].sort(),['dast','device-tools','files','frida','proxy','reverse']);
});

// --- revealPhase: document stub mínimo ---
function classList(init){const s=new Set(init);return{add:x=>s.add(x),remove:x=>s.delete(x),toggle:(x,on)=>{if(on)s.add(x);else s.delete(x);},contains:x=>s.has(x)};}
function makeDoc(hidden=[]){
 const tabs=['device-tools','files','reverse','dast','frida','proxy'];
 const phases=['engagement','estatico','dinamico'].map(p=>({dataset:{phase:p},classList:classList(),setAttribute(){}}));
 const nav={},panel={};const router={hidden:true};const extra={'#phaseEmpty':{hidden:false},'.tool-router':router};
 // Os botões da sub-nav são os mesmos nós consultados por [data-tab="id"]: um
 // só objeto por aba, com classList/setAttribute para off-phase/active/aria.
 tabs.forEach(id=>{nav[id]={dataset:{tab:id},hidden:hidden.includes(id),disabled:false,classList:classList(),aria:{},setAttribute(k,v){this.aria[k]=v;}};panel[id]={id:'tab-'+id,classList:classList()};});
 return {phases,nav,panel,router,extra,
  querySelectorAll(sel){if(sel==='.phase-spine .phase')return phases;if(sel==='.tab-content')return tabs.map(id=>panel[id]);if(sel==='.tool-router [data-tab]')return tabs.map(id=>nav[id]);return[];},
  querySelector(sel){let m;if((m=sel.match(/^\[data-tab="(.+)"\]$/)))return nav[m[1]]||null;if((m=sel.match(/^#tab-(.+)$/)))return panel[m[1]]||null;return extra[sel]||null;}};
}
function makeChipDoc(){const el=()=>({textContent:'',hidden:false,classList:classList()});const n={'#workbenchDeviceDot':el(),'#workbenchDeviceChip':el(),'#workbenchDeviceBadge':el()};return{n,querySelector:s=>n[s]||null};}

test('revealPhase mostra só a aba ativa (default = primeira) e devolve {available,active}',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase('dinamico',doc),{available:['dast','frida','proxy'],active:'dast'});
 assert.ok(doc.panel['dast'].classList.contains('active'));
 assert.ok(!doc.panel['frida'].classList.contains('active'));
 assert.ok(!doc.panel['proxy'].classList.contains('active'));
 assert.ok(doc.phases.find(p=>p.dataset.phase==='dinamico').classList.contains('active'));
});
test('revealPhase marca a sub-aba ativa e esconde as abas fora da fase',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 revealPhase('dinamico',doc);
 // dast/frida/proxy pertencem à fase (não off-phase); device-tools não
 assert.ok(!doc.nav['dast'].classList.contains('off-phase'));
 assert.ok(!doc.nav['proxy'].classList.contains('off-phase'));
 assert.ok(doc.nav['device-tools'].classList.contains('off-phase'));
 assert.ok(doc.nav['reverse'].classList.contains('off-phase'));
 // só a ativa recebe .active + aria-selected=true
 assert.ok(doc.nav['dast'].classList.contains('active'));
 assert.equal(doc.nav['dast'].aria['aria-selected'],'true');
 assert.ok(!doc.nav['frida'].classList.contains('active'));
 assert.equal(doc.nav['frida'].aria['aria-selected'],'false');
});
test('revealPhase respeita a aba pedida quando disponível',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase('dinamico',doc,'proxy'),{available:['dast','frida','proxy'],active:'proxy'});
 assert.ok(doc.panel['proxy'].classList.contains('active'));
 assert.ok(!doc.panel['dast'].classList.contains('active'));
 assert.ok(doc.nav['proxy'].classList.contains('active'));
});
test('aba pedida indisponível ou inválida cai na primeira disponível',()=>{
 const {revealPhase}=load();
 assert.equal(revealPhase('dinamico',makeDoc(),'inexistente').active,'dast');
 assert.equal(revealPhase('dinamico',makeDoc(['dast']),'dast').active,'frida');
});
test('fase com uma só aba disponível esconde a sub-nav',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase('estatico',doc),{available:['reverse'],active:'reverse'});
 assert.equal(doc.router.hidden,true);
});
test('fase com duas ou mais abas mostra a sub-nav',()=>{
 const {revealPhase}=load();const doc=makeDoc();
 revealPhase('dinamico',doc);
 assert.equal(doc.router.hidden,false);
});
test('fase sem abas disponíveis: active undefined, sub-nav escondida e aviso visível',()=>{
 const {revealPhase}=load();const doc=makeDoc(['reverse']);
 assert.deepEqual(revealPhase('estatico',doc),{available:[],active:undefined});
 assert.ok(!doc.panel['reverse'].classList.contains('active'));
 assert.equal(doc.router.hidden,true);
 assert.equal(doc.extra['#phaseEmpty'].hidden,false);
});
test('preferencia invalida restaura a fase engagement',()=>{
 const {revealPhase,phaseForTab}=load();const doc=makeDoc();
 assert.deepEqual(revealPhase(phaseForTab('xxx'),doc),{available:['device-tools','files'],active:'device-tools'});
});
test('revealPhase esconde o aviso de fase vazia quando ha abas, e o mostra quando nao ha',()=>{
 const {revealPhase}=load();
 const doc=makeDoc();revealPhase('dinamico',doc);
 assert.equal(doc.extra['#phaseEmpty'].hidden,true);
 const docEmpty=makeDoc(['reverse']);revealPhase('estatico',docEmpty);
 assert.equal(docEmpty.extra['#phaseEmpty'].hidden,false);
});
test('updateWorkbenchChip reflete rotulo, online e perfil reais',()=>{
 const {updateWorkbenchChip}=load();const doc=makeChipDoc();
 updateWorkbenchChip({label:'Principal · emulator-5556 · Online',online:true,profile:'Google Play · sem root'},doc);
 assert.equal(doc.n['#workbenchDeviceChip'].textContent,'Principal · emulator-5556 · Online');
 assert.ok(doc.n['#workbenchDeviceDot'].classList.contains('on'));
 assert.ok(!doc.n['#workbenchDeviceDot'].classList.contains('off'));
 assert.equal(doc.n['#workbenchDeviceBadge'].hidden,false);
 assert.equal(doc.n['#workbenchDeviceBadge'].textContent,'Google Play · sem root');
});
test('updateWorkbenchChip marca offline e esconde badge sem perfil',()=>{
 const {updateWorkbenchChip}=load();const doc=makeChipDoc();
 updateWorkbenchChip({label:'Principal · — · Desligado',online:false,profile:null},doc);
 assert.ok(doc.n['#workbenchDeviceDot'].classList.contains('off'));
 assert.ok(!doc.n['#workbenchDeviceDot'].classList.contains('on'));
 assert.equal(doc.n['#workbenchDeviceBadge'].hidden,true);
});
