const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const html=()=>fs.readFileSync('web/index.html','utf8');

test('o painel tem a espinha de 3 fases (Evidencias saiu do topo)',()=>{
 const h=html();
 for(const p of ['engagement','estatico','dinamico']) assert.match(h,new RegExp(`data-phase="${p}"`));
 assert.doesNotMatch(h,/data-phase="evidencias"/);
 assert.match(h,/phase-spine/);
});
test('o contador de evidencias vive no popup de evidencias',()=>{
 const h=html();
 assert.ok(h.indexOf('id="evidenceCount"')>h.indexOf('id="evidenceDialog"'),'evidenceCount deve viver dentro do dialog de evidencias');
});
test('a navegacao paralela por grupos foi removida',()=>{
 assert.doesNotMatch(html(),/tool-group-label/);
});
test('os contratos de DOM que o JS depende continuam presentes',()=>{
 const h=html();
 for(const id of ['analysisPanel','analysisToggle','analysisChevron','analysisToggleLabel','evidenceCount']) assert.match(h,new RegExp(`id="${id}"`));
 for(const tab of ['device-tools','files','reverse','dast','frida','proxy']) assert.match(h,new RegExp(`data-tab="${tab}"`));
 assert.doesNotMatch(h,/data-tab="evidence"/);
});
test('o contador de evidencias existe exatamente uma vez',()=>{
 const matches=html().match(/id="evidenceCount"/g)||[];
 assert.equal(matches.length,1);
});
test('o icone solto de evidencias saiu do header do topo',()=>{
 assert.doesNotMatch(html(),/aria-label="Abrir evidências"/);
});
test('o visor de arquivo existe com os contratos de DOM que o clique usa',()=>{
 const h=html();
 assert.match(h,/id="fileViewer"/);
 for(const id of ['fileViewerSource','fileViewerPath','fileViewerMeta','fileViewerContent','fileViewerClose']) assert.match(h,new RegExp(`id="${id}"`));
});
test('o painel Estatico tem o seletor de app proprio, antes do visor de reversePackage',()=>{
 const h=html();
 assert.match(h,/id="reverseAppPicker"/);
 // o seletor vive no cabecalho do painel estatico, junto do reversePackage
 assert.ok(h.indexOf('id="reverseAppPicker"')<h.indexOf('id="refreshApps"'),'o seletor precede o botao Atualizar apps');
});
test('os scripts de bypass curados vivem catalogados e desabilitados na secao gated',()=>{
 const h=html();
 const gated=h.slice(h.indexOf('unavailable-scripts'));
 for(const value of ['tls-unpin-multi','root-jailbreak-bypass','anti-frida-bypass','webview-debug-enable','rasp-bypass']){
  assert.match(gated,new RegExp(`value="${value}" disabled`),value);
 }
 // o preset de RASP aponta que recebe o script revisado do operador
 assert.match(gated,/preset do operador/i);
});
