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
test('o botao Ligar existe no cabecalho do palco, ao lado do Desligar',()=>{
 const h=html();
 assert.match(h,/id="powerOnDevice"/);
 // o Ligar vive no mesmo cabecalho do palco que o Desligar (closeLabButton)
 const header=h.slice(h.indexOf('id="runtimeState"'),h.indexOf('id="runtimePlaceholder"'));
 assert.match(header,/id="powerOnDevice"/);
 assert.match(header,/id="closeLabButton"/);
});
test('o cartao de identidade Android (trocar Android ID) existe no painel de ferramentas',()=>{
 const h=html();
 const at=h.indexOf('id="androidIdentityCard"');
 const open=h.slice(h.lastIndexOf('<section',at),at);
 assert.match(open,/platform-android/,'o cartao Android fica visivel so no modo Android');
 const card=h.slice(at,at+1200);
 for(const id of ['androidIdentityValue','androidIdInput','applyAndroidId','randomAndroidId']) assert.match(card,new RegExp(`id="${id}"`),id);
});
test('o painel Estatico tem o cartao de proteções/RASP (fatia nutcracker)',()=>{
 const h=html();
 const panel=h.slice(h.indexOf('id="tab-reverse"'),h.indexOf('id="reverseOutput"'));
 for(const id of ['protectionScan','refreshProtections','protectionSummary','protectionList']) assert.match(panel,new RegExp(`id="${id}"`),id);
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
