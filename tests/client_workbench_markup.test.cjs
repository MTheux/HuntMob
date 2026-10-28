const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const html=()=>fs.readFileSync('web/index.html','utf8');

test('o painel tem a espinha de 4 fases',()=>{
 const h=html();
 for(const p of ['engagement','estatico','dinamico','evidencias']) assert.match(h,new RegExp(`data-phase="${p}"`));
 assert.match(h,/phase-spine/);
});
test('o contador de evidencias vive na espinha, nao antes dela',()=>{
 const h=html();
 assert.ok(h.indexOf('id="evidenceCount"')>h.indexOf('phase-spine'),'evidenceCount deve aparecer dentro/depois da espinha');
});
test('a navegacao paralela por grupos foi removida',()=>{
 assert.doesNotMatch(html(),/tool-group-label/);
});
test('os contratos de DOM que o JS depende continuam presentes',()=>{
 const h=html();
 for(const id of ['analysisPanel','analysisToggle','analysisChevron','analysisToggleLabel','evidenceCount']) assert.match(h,new RegExp(`id="${id}"`));
 for(const tab of ['device-tools','files','reverse','dast','frida','proxy','evidence']) assert.match(h,new RegExp(`data-tab="${tab}"`));
});
test('o contador de evidencias existe exatamente uma vez',()=>{
 const matches=html().match(/id="evidenceCount"/g)||[];
 assert.equal(matches.length,1);
});
test('o icone solto de evidencias saiu do header do topo',()=>{
 assert.doesNotMatch(html(),/aria-label="Abrir evidências"/);
});
