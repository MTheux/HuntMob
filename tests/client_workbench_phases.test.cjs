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
