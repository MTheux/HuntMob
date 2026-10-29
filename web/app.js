let devicePlatform = 'android';
const tabs = document.querySelectorAll('.analysis-tabs button');
const panels = document.querySelectorAll('.tab-content');
const toast = document.querySelector('.toast');
const dialog = document.querySelector('#fixtureDialog');
const preview = document.querySelector('#cameraPreview');
const overlay = document.querySelector('#faceOverlay');
const faceStatus = document.querySelector('#faceStatus');
const enrollFace = document.querySelector('#enrollFace');
const verifyFace = document.querySelector('#verifyFace');
const newLabDialog = document.querySelector('#newLabDialog');
let stream;
let human;
let enrolledEmbedding;
let runtimeDevice;
let screenTimer;
let csrfToken;
let runtimeLoading = false;
let runtimeWasOnline = false;
let activeLab = {};
let labLifecycleBusy = false;
function labIsSaved(lab = activeLab) {
  return !!lab?.id && (!Object.hasOwn(lab, 'saved_at') || lab.saved_at !== null);
}
function syncLabLifecycleButtons() {
  const available = devicePlatform === 'android' && !!activeLab.id && !labLifecycleBusy;
  const saveButton = document.querySelector('#saveLabButton');
  const closeButton = document.querySelector('#closeLabButton');
  saveButton.disabled = !available || labIsSaved();
  saveButton.textContent = labIsSaved() ? 'Lab salvo' : 'Salvar laboratório';
  closeButton.disabled = !available;
}
function renderEngagement(lab) {
  // Project metadata remains in the lab profile; no placeholder in the header.
}
let analysisReady = false;
let reverseAnalysis;
let reverseFileRequest = 0;
let observedLabId = "";
const reverseInitialHtml = document.querySelector('#reverseOutput').innerHTML;

const workspace = document.querySelector('#workspace');
const analysisPanel = document.querySelector('#analysisPanel');
function setProxyFocus(focused) {
  workspace.classList.toggle('proxy-focus', focused);
  const button = document.querySelector('#proxyFocusToggle');
  button.textContent = focused ? 'Mostrar Android' : 'Expandir área';
  button.setAttribute('aria-pressed', String(focused));
  window.huntmobCanvas?.resize();
}
let analysisPreference = null;
try { analysisPreference = localStorage.getItem('huntmob.analysisOpen'); } catch {}
function setAnalysisOpen(open, remember = false) {
  if (!open) setProxyFocus(false);
  workspace.classList.toggle('analysis-collapsed', !open);
  analysisPanel.hidden = !open;
  document.querySelector('#analysisToggle').setAttribute('aria-expanded', String(open));
  document.querySelector('#analysisToggle').title = open ? 'Ocultar ferramentas' : 'Abrir ferramentas';
  document.querySelector('#analysisChevron').textContent = open ? '›' : '‹';
  document.querySelector('#analysisToggleLabel').textContent = open ? 'Ocultar' : 'Ferramentas';
  if (remember) {
    analysisPreference = String(open);
    try { localStorage.setItem('huntmob.analysisOpen', analysisPreference); } catch {}
  }
}
document.querySelector('#analysisToggle').addEventListener('click', () => {
  setAnalysisOpen(analysisPanel.hidden, true);
});
function syncAnalysisAvailability(online) {
  setAnalysisOpen(online && analysisPreference !== 'false');
}

const viewport = document.querySelector('#deviceViewport');
const phoneCanvas = document.querySelector('#phoneCanvas');
let deviceZoom = 1;
function setDeviceZoom(value, {automatic=false} = {}) {
  if(!automatic)window.huntmobCanvas?.manual();
  deviceZoom = Math.min(2.5, Math.max(0.5, Math.round(value * 100) / 100));
  phoneCanvas.style.setProperty('--device-zoom', deviceZoom);
  window.huntmobCanvas?.resize();
  document.querySelector('#zoomValue').textContent = `${Math.round(deviceZoom * 100)}%`;
  document.querySelector('#zoomOut').disabled = deviceZoom <= 0.5;
  document.querySelector('#zoomIn').disabled = deviceZoom >= 2.5;
}
document.querySelector('#zoomOut').addEventListener('click', () => setDeviceZoom(deviceZoom - 0.1));
document.querySelector('#zoomIn').addEventListener('click', () => setDeviceZoom(deviceZoom + 0.1));
document.querySelector('#zoomFit').addEventListener('click', () => {
  if(window.huntmobCanvas?.fit())return;
  setDeviceZoom(1);
  if(phoneCanvas.classList.contains('has-companions')){
    const tiles=[...phoneCanvas.querySelectorAll('.device-tile')];
    const style=getComputedStyle(phoneCanvas);
    const width=tiles.reduce((sum,tile)=>sum+tile.getBoundingClientRect().width,0)+Math.max(0,tiles.length-1)*parseFloat(style.gap);
    const height=Math.max(...tiles.map(tile=>tile.getBoundingClientRect().height),1);
    setDeviceZoom(Math.min(1,(phoneCanvas.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight))/width,(phoneCanvas.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom))/height));
    phoneCanvas.scrollTo({top:0,left:0});
  }
  viewport.scrollTo({ top: 0, left: 0 });
});
viewport.addEventListener('wheel', event => {
  // Preserve browser accessibility zoom and scrolling over the tool buttons.
  if (event.ctrlKey || event.metaKey || event.target.closest('button,input,select,textarea,.device-controls,.workspace-selection-tools') || viewport.classList.contains('runtime-unavailable')) return;
  event.preventDefault();
  const delta = (event.deltaY||event.deltaX) * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1);
  const next=deviceZoom * Math.exp(-Math.max(-100, Math.min(100, delta)) * 0.002);
  if(!window.huntmobCanvas?.zoomAt(next,event.clientX,event.clientY))setDeviceZoom(next);
}, { passive: false });
let viewportPan;
viewport.addEventListener('pointerdown',event=>{
  if(event.button!==1||event.target.closest('button,input,select,textarea,a')||viewport.classList.contains('runtime-unavailable'))return;
  event.preventDefault();event.stopPropagation();
  viewportPan={id:event.pointerId,x:event.clientX,y:event.clientY};viewport.setPointerCapture(event.pointerId);viewport.classList.add('viewport-panning');
},{capture:true});
viewport.addEventListener('pointermove',event=>{
  if(viewportPan?.id!==event.pointerId)return;
  event.preventDefault();const dx=event.clientX-viewportPan.x,dy=event.clientY-viewportPan.y;viewportPan.x=event.clientX;viewportPan.y=event.clientY;
  if(!window.huntmobCanvas?.panBy(dx,dy)){viewport.scrollLeft-=dx;viewport.scrollTop-=dy;}
});
function finishViewportPan(event){if(!viewportPan||(event?.pointerId!==undefined&&event.pointerId!==viewportPan.id))return;const id=viewportPan.id;viewportPan=undefined;viewport.classList.remove('viewport-panning');if(viewport.hasPointerCapture(id))viewport.releasePointerCapture(id);}
for(const type of ['pointerup','pointercancel','lostpointercapture'])viewport.addEventListener(type,finishViewportPan);
viewport.addEventListener('auxclick',event=>{if(event.button===1)event.preventDefault();});
window.addEventListener('blur',()=>finishViewportPan());
setDeviceZoom(1);


async function sessionFetch(route, options) {
  async function send() {
    if(!csrfToken)csrfToken=await fetchSessionToken();
    return fetch(route,{...options,headers:{...options.headers,'X-HuntMob-CSRF':csrfToken}});
  }
  let response=await send();
  if(response.status===403 && (response.headers.get('content-type') || '').includes('application/json')){
    const rejection=await response.clone().json();
    if(rejection.error_code==='csrf_session_changed' && rejection.executed===false){
      csrfToken=undefined;response=await send();
    }
  }
  if(!(response.headers.get('content-type') || '').includes('application/json'))throw new Error(`Servidor recusou a operação (${response.status}). Reconecte a sessão.`);
  return response;
}

async function authorizedPost(route, body) {
  if (devicePlatform === 'ios' && ['/api/reverse','/api/dynamic','/api/proxy','/api/network/send'].includes(route)) {
    throw new Error('Esta ação ainda não está integrada ao runtime iOS.');
  }
  if (!csrfToken) csrfToken = await fetchSessionToken();
  const response = await sessionFetch(route, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-HuntMob-CSRF': csrfToken },
    body: JSON.stringify({ ...body, authorized: true, approved: true }),
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.reason || `ação recusada (${response.status})`);
    error.payload = payload;
    throw error;
  }
  return payload;
}

async function deviceAction(action, options = {}) {
  return authorizedPost('/api/device/action', { action, ...options });
}

let screenConnected = false;
let screenGeneration = 0;
let screenRetries = 0;
function stopDeviceScreen() {
  stopIosCanvas();
  screenConnected=false;
  screenGeneration += 1; stopDirectVideo();
  window.clearTimeout(screenTimer);
  const screen = document.querySelector('#deviceScreen');
  screen.onload = screen.onerror = null;
  screen.removeAttribute('src');
  screen.hidden = true;
  document.querySelector('#screenConnection').textContent = 'Tela desconectada';
}
function startDeviceScreen() {
  stopDeviceScreen();
  directVideoFailures=0;
  screenConnected=true;
  document.querySelector('.phone-screen').hidden = true;
  const generation = screenGeneration;
  if (devicePlatform === 'ios') { startIosScreen(generation); return; }
  if (window.VideoDecoder) { startDirectVideo(generation); return; }
  startCompatibleScreen(generation);
}
function startCompatibleScreen(generation) {
  const screen = document.querySelector('#deviceScreen');
  document.querySelector('#screenConnection').textContent = screenRetries ? 'Reconectando tela…' : 'Conectando tela…';
  screen.onload = () => {
    if (generation !== screenGeneration || runtimeDevice?.state !== 'on') return;
    screenRetries = 0;
    screen.hidden = false;
    fitPhoneFrame(screen,screen.naturalWidth,screen.naturalHeight,'android');
    document.querySelector('.phone-screen').hidden = true;
    document.querySelector('#screenConnection').textContent = 'Tela conectada · scroll para ampliar';
  };
  screen.onerror = () => {
    if (generation !== screenGeneration || runtimeDevice?.state !== 'on') return;
    screen.hidden = true;
    document.querySelector('.phone-screen').hidden = true;
    const delay = Math.min(15000, 1000 * 2 ** Math.min(screenRetries++, 4));
    document.querySelector('#screenConnection').textContent = `Tela indisponível · nova tentativa em ${delay / 1000}s`;
    screenTimer = window.setTimeout(() => {
      if (generation === screenGeneration && runtimeDevice?.state === 'on') startDeviceScreen();
    }, delay);
  };
  screen.dataset.frameWidth = '540';
  screen.dataset.frameHeight = '1200';
  window.huntmobOperator.mediaUrl(`/api/device/stream?t=${Date.now()}`).then(url=>{if(generation===screenGeneration)screen.src=url;}).catch(()=>screen.onerror?.());
}
document.querySelector('#reconnectScreen').addEventListener('click', () => {
  screenRetries = 0;
  if (runtimeDevice?.state === 'on') startDeviceScreen();
});

let rootProfileBusy = false;
let rootProfileKnownId = null;
document.querySelector('#prepareRootProfile').addEventListener('click', async event => {
  if (rootProfileBusy) return;
  rootProfileBusy = true;
  const button = event.currentTarget;
  button.disabled = true; button.textContent = 'Preparando imagem…';
  document.querySelector('#rootProfileStatus').textContent = 'Baixando imagem oficial Android, se necessário…';
  try { await deviceAction('prepare-root-profile', {root_mode: document.querySelector('#deviceRootMode').value}); notify('Imagem pronta para este perfil'); }
  catch (error) { notify(error.message); }
  finally { rootProfileBusy = false; button.disabled = false; button.textContent = 'Preparar imagem'; }
});
async function changeAndroidRootProfile(mode, expectedLabId=activeLab.id) {
  if(rootProfileBusy)return {ok:false,reason:'Aguarde a troca de perfil em andamento.'};
  if(devicePlatform!=='android'||expectedLabId!==activeLab.id){notify('O aparelho selecionado mudou. Abra Root novamente.');return {ok:false,reason:'O aparelho selecionado mudou. Abra Root novamente.'};}
  if(mode===(activeLab.root_mode||'root')){notify('Este perfil já está selecionado');return {ok:true};}
  rootProfileBusy=true;
  const button=document.querySelector('#switchRootProfile');button.disabled=true;button.textContent='Trocando Android…';
  document.querySelector('#rootProfileStatus').textContent='Preparando a imagem oficial do outro Android…';
  try{
    await deviceAction('prepare-root-profile',{root_mode:mode});
    document.querySelector('#rootProfileStatus').textContent='Preservando o Android atual e iniciando o outro…';
    stopDeviceScreen();
    const result=await deviceAction('root-profile',{root_mode:mode,lab_id:expectedLabId});
    await loadRuntime();await loadSavedLabs();await loadWorkspaceDevices();
    if(result.lab?.package_id)selectApp(result.lab.package_id);
    notify('Android trocado. O anterior continua preservado; os dados do app são separados.');return result;
  }catch(error){notify(error.message);return {ok:false,reason:error.message};}
  finally{rootProfileBusy=false;button.disabled=false;button.textContent='Trocar perfil';await loadRuntime();}
}
document.querySelector('#switchRootProfile').addEventListener('click',()=>changeAndroidRootProfile(document.querySelector('#deviceRootMode').value));

async function loadRuntime() {
  if (devicePlatform === 'ios') { await loadIosRuntime(true); return; }
  if (runtimeLoading) return;
  runtimeLoading = true;
  try {
    const response = await fetch('/api/runtime', { cache: 'no-store', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error(`runtime API ${response.status}`);
    const payload = await response.json();
    const changingRoot=window.huntmobTools?.rootChanging?.();
    if(changingRoot&&!payload.devices?.length&&payload.lab?.id===changingRoot)return;
    window.huntmobSidebar?.runtime(payload);
    if (devicePlatform !== 'android') {
      const android = payload.devices?.[0];
      document.querySelector('#runtimeName').textContent = android?.name || 'Android · desligado';
      document.querySelector('#runtimeMeta').textContent = android ? `Android ${android.android_version} · API ${android.api}` : 'Worker Android local';
      document.querySelector('#runtimeCount').textContent = android ? '1' : '0';
      document.querySelector('#runtimeDot').className = android ? 'online-dot' : 'offline-dot';
      return;
    }
    activeLab = payload.lab || {};
    engagementBound = !!activeLab.engagement; syncEngagementStepper();
    syncLabLifecycleButtons();
    renderEngagement(activeLab);
    const verification = activeLab.root_verification;
    document.querySelector('#rootProfileStatus').textContent = verification?.verified ? (activeLab.root_mode==='stock' ? 'Google Play · ADB root indisponível' : 'AOSP · ADB root alternável em Controles') : 'Imagem ainda não verificada';
    if (!rootProfileBusy && rootProfileKnownId !== activeLab.id) {
      rootProfileKnownId = activeLab.id;
      document.querySelector('#deviceRootMode').value = activeLab.root_mode || 'root';
    }
    document.querySelector('#switchRootProfile').disabled = rootProfileBusy || !activeLab.id;
    const labChanged = (activeLab.id || '') !== observedLabId;
    if (labChanged) {
      observedLabId = activeLab.id || '';
      stopDeviceScreen();
      runtimeWasOnline = false;
      currentSelectedPackage = '';
      packageId.value = activeLab.package_id || '';
      reverseAnalysis = undefined;
      reverseFileRequest += 1;
      document.querySelector('#reverseOutput').innerHTML = reverseInitialHtml;
      networkSelection = undefined;
      networkFlows = [];
      document.querySelector('#requestEditor').value = '';
      document.querySelector('#responseEditor').textContent = 'Selecione uma requisição deste lab.';
      document.querySelector('#reverseHash').textContent = 'SHA256 pendente';
      document.querySelector('#openGhidra').disabled = true;
      document.querySelector('#reversePackage').textContent = 'Selecione um aplicativo';
      document.querySelector('#targetAppState').textContent = 'Nenhum app selecionado';
      document.querySelector('#prepareReverse')?.setAttribute('disabled', '');
      loadSavedLabs();
      loadEvidence();
      clearReportDetails(); nativeReportJob = '';
      document.querySelector('#nativeCoverage').replaceChildren();
      document.querySelector('#nativeCandidates').replaceChildren();
      document.querySelector('#nativeReportJson').hidden = true;
      document.querySelector('#nativeReportHtml').hidden = true;
      document.querySelector('#nativeReportStatus').textContent = 'Nenhuma análise carregada para este laboratório.';
      loadNativeReport();
    }
    runtimeDevice = payload.devices?.[0];
    window.huntmobTools?.refreshRoot?.();
    document.querySelector('#runtimeCount').textContent = String((payload.devices?.length || 0)+(window.huntmobAdditionalOnline?.()||0));
    if (!runtimeDevice) {
      const workerReady = payload.ready === true;
      if (runtimeWasOnline || analysisPreference === null) syncAnalysisAvailability(false);
      if (runtimeWasOnline) stopDeviceScreen();
      runtimeWasOnline = false;
      document.querySelector('#runtimeDevice').hidden = true;
      document.querySelector('#runtimeEmpty').hidden = false;
      document.querySelector('#deviceScreen').hidden = true;
      document.querySelector('#deviceScreen').removeAttribute('src');
      document.querySelector('.phone-screen').hidden = false;
      document.querySelector('#runtimeName').textContent = workerReady ? 'Worker pronto · device desligado' : 'Runtime próprio em construção';
      document.querySelector('#runtimeMeta').textContent = workerReady ? 'Android Emulator e imagem AOSP instalados' : (payload.limitations?.join(' · ') || 'Imagem AOSP HuntMob necessária');
      document.querySelector('#stageDeviceName').textContent = 'HuntMob Runtime';
      document.querySelector('#stageSerial').textContent = workerReady ? 'nenhum device em execução' : 'QEMU/AOSP ainda não provisionado';
      const runtimeLabels = { booting: 'INICIANDO', unauthorized: 'AUTORIZAÇÃO PENDENTE', error: 'ERRO ADB' };
      document.querySelector('#runtimeState').textContent = runtimeLabels[payload.state] || (workerReady ? 'STOPPED' : 'BUILD REQUIRED');
      document.querySelector('#deviceViewport').classList.add('runtime-unavailable');
      document.querySelector('#runtimePlaceholder').hidden = false;
      document.querySelector('#runtimePlaceholder strong').textContent = workerReady ? 'Device desligado' : 'Runtime ainda não provisionado';
      document.querySelector('#runtimePlaceholder span').textContent = payload.state === 'booting' ? 'Android iniciando · aguardando conclusão do boot' : payload.connection?.reason || (workerReady ? 'Worker e imagem prontos · crie ou inicie um laboratório' : 'Instale o runtime para preparar seu laboratório');
      document.querySelectorAll('.toolbar-actions button').forEach((button) => { button.disabled = true; });
      document.querySelector('#eventKind').textContent = 'STATE';
      document.querySelector('#eventMessage').textContent = workerReady ? 'Worker pronto; inicie um laboratório' : 'Nenhuma VM HuntMob em execução';
      document.querySelector('#eventReceipt').textContent = 'sem receipt';
      const status = document.querySelector('#biometricStatus');
      status.textContent = 'Aguardando o HAL biométrico da imagem AOSP HuntMob';
      status.className = 'face-status error';
      document.querySelectorAll('[data-biometric]').forEach((button) => { button.disabled = true; });
      document.querySelector('#automaticBiometric').disabled = true;
      return;
    }
    const online = runtimeDevice.state === 'on';
    if (online !== runtimeWasOnline) syncAnalysisAvailability(online);
    document.querySelector('#runtimeDevice').hidden = false;
    document.querySelector('#runtimeEmpty').hidden = true;
    document.querySelectorAll('.toolbar-actions button').forEach((button) => { button.disabled = !online; });
    document.querySelector('#deviceViewport').classList.toggle('runtime-unavailable', !online);
    document.querySelector('#runtimePlaceholder').hidden = online;
    if (!online) {
      window.clearTimeout(screenTimer);
      document.querySelector('#deviceScreen').hidden = true;
      document.querySelector('#deviceScreen').removeAttribute('src');
      document.querySelector('#runtimePlaceholder strong').textContent = 'Device desconectado';
      document.querySelector('#runtimePlaceholder span').textContent = 'Aguardando o Android ficar online';
    }
    if (online && (!runtimeWasOnline || !screenConnected)) startDeviceScreen();
    if (online && !runtimeWasOnline) {
      loadInstalledApps();
      refreshProxyStatus();
    }
    runtimeWasOnline = online;
    if (online) {
      document.querySelector('#eventTime').textContent = new Date().toLocaleTimeString('pt-BR');
      document.querySelector('#eventKind').textContent = 'READY';
      document.querySelector('#eventMessage').textContent = 'Android HuntMob inicializado em modo headless';
      document.querySelector('#eventReceipt').textContent = 'runtime observado';
    }
    document.querySelector('#runtimeName').textContent = runtimeDevice.name;
    document.querySelector('#runtimeMeta').textContent = `Android ${runtimeDevice.android_version} · API ${runtimeDevice.api} · ${runtimeDevice.architecture}`;
    document.querySelector('#stageDeviceName').textContent = runtimeDevice.name;
    document.querySelector('#stageSerial').textContent = runtimeDevice.adb_serial || 'ADB indisponível';
    document.querySelector('#runtimeState').textContent = online ? 'ONLINE' : runtimeDevice.state.toUpperCase();
    const dot = document.querySelector('#runtimeDot');
    dot.className = online ? 'online-dot' : 'offline-dot';
    dot.setAttribute('aria-label', online ? 'Online' : 'Offline');
    window.huntmobBiometrics?.refresh();
  } catch (error) {
    document.querySelector('#runtimeName').textContent = 'Runtime indisponível';
    window.huntmobSidebar?.runtimeError();
    document.querySelector('#runtimeMeta').textContent = error.message;
    document.querySelector('#runtimeState').textContent = 'OFFLINE';
    stopDeviceScreen();
    runtimeDevice = undefined;
    document.querySelectorAll('.toolbar-actions button').forEach(button => { button.disabled = true; });
    document.querySelector('#deviceViewport').classList.add('runtime-unavailable');
    document.querySelector('#runtimePlaceholder').hidden = false;
    document.querySelector('#runtimePlaceholder strong').textContent = 'Worker indisponível';
    document.querySelector('#runtimePlaceholder span').textContent = 'Verifique o servidor local. A conexão será tentada novamente.';
    syncAnalysisAvailability(false);
    runtimeWasOnline = false;
  } finally {
    runtimeLoading = false;
    window.huntmobSidebar?.sync();
    window.huntmobDastApps?.sync();
  }
}

function setFaceStatus(message, state = '') {
  faceStatus.textContent = message;
  faceStatus.className = `face-status ${state}`.trim();
}

async function loadFaceEngine() {
  if (!window.Human?.Human) throw new Error('biblioteca facial indisponível');
  if (human) return human;
  human = new window.Human.Human({
    backend: 'webgl',
    modelBasePath: 'https://vladmandic.github.io/human-models/models/',
    face: {
      enabled: true,
      detector: { enabled: true, rotation: true, return: true },
      mesh: { enabled: true },
      description: { enabled: true },
      iris: { enabled: true },
      antispoof: { enabled: true },
      liveness: { enabled: true },
      emotion: { enabled: false },
    },
    body: { enabled: false },
    hand: { enabled: false },
    object: { enabled: false },
    gesture: { enabled: true },
  });
  setFaceStatus('Carregando modelos faciais…');
  await human.load();
  await human.warmup();
  return human;
}

async function captureFace() {
  if (!human || !stream) throw new Error('ative a webcam primeiro');
  const result = await human.detect(preview);
  overlay.width = preview.videoWidth || 640;
  overlay.height = preview.videoHeight || 480;
  const context = overlay.getContext('2d');
  context.clearRect(0, 0, overlay.width, overlay.height);
  await human.draw.face(overlay, result.face);
  if (result.face.length !== 1) throw new Error('mantenha exatamente um rosto visível');
  const face = result.face[0];
  const confidence = face.faceScore || face.boxScore || 0;
  if (confidence < 0.6) throw new Error('rosto detectado com baixa confiança');
  if (!face.embedding?.length) throw new Error('não foi possível gerar o embedding');
  return face;
}

function notify(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
}

// Qualquer clique numa aba (do usuário ou programático via [data-tab].click())
// é delegado à fase dona da aba: uma taxonomia só.
tabs.forEach((tab) => tab.addEventListener('click', () => {
  if (tab.hidden || tab.disabled) return;
  activatePhase(phaseForTab(tab.dataset.tab), tab.dataset.tab);
}));

// A fase revela UMA sub-aba por vez (a pedida, senão a primeira disponível) e
// dispara os efeitos da aba que ficou ativa. Entrar pela espinha (sem tab) cai
// na primeira aba da fase; clicar numa sub-aba traz a sua.
function activatePhase(phase, tab) {
  if (!tabsForPhase(phase).length) phase = 'engagement';
  setAnalysisOpen(true, true);
  const { active } = revealPhase(phase, document, tab);
  try { localStorage.setItem('huntmob.activePhase', phase); } catch {}
  if (active !== 'proxy') setProxyFocus(false);
  if (active === 'dast' && devicePlatform === 'android') { loadNativeReport(); refreshDynamic().then(() => window.huntmobDastApps?.load()); refreshDeepDast(); }
  if (active === 'frida' && devicePlatform === 'android') refreshDynamic();
  if (active === 'proxy' && devicePlatform === 'android') { loadNetwork(); refreshProxyStatus(); }
  syncEngagementStepper();
}
document.querySelectorAll('.phase-spine .phase').forEach((button) => button.addEventListener('click', () => activatePhase(button.dataset.phase)));

// Stepper global do engagement: reflete o estado real das fases do pentest
// (engagement → estático → dinâmico → evidências) lendo sinais já rastreados.
// Aditivo: não altera os fluxos das abas; apenas lê e navega.
let engagementBound = false;
function syncEngagementStepper() {
  const stepper = document.querySelector('#engagementStepper');
  if (!stepper) return;
  const evidence = Number.parseInt(document.querySelector('#evidenceCount')?.textContent, 10) || 0;
  const done = { engagement: engagementBound, estatico: !!reverseAnalysis, dinamico: !!dastProgressReport, evidencias: evidence > 0 };
  const order = ['engagement', 'estatico', 'dinamico', 'evidencias'];
  const current = order.findIndex((phase) => !done[phase]);
  order.forEach((phase, index) => {
    const btn = stepper.querySelector(`.phase[data-phase="${phase}"]`);
    if (!btn) return;
    btn.dataset.state = done[phase] ? 'done' : index === current ? 'current' : 'pending';
    btn.classList.toggle('done', done[phase]);
  });
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  const view = button.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === button));
  if (view === 'device') { setAnalysisOpen(false, true); return; }
  const tab = { reverse: 'reverse', traffic: 'proxy', scripts: 'frida' }[view];
  if (tab) document.querySelector(`[data-tab="${tab}"]`).click();
}));

document.querySelectorAll('.file').forEach((file) => file.addEventListener('click', () => {
  document.querySelectorAll('.file').forEach((item) => item.classList.remove('selected'));
  file.classList.add('selected');
  document.querySelector('#fileName').textContent = file.dataset.file || file.textContent;
  notify(`Arquivo selecionado: ${file.textContent.trim()}`);
}));

document.querySelectorAll('[data-panel]').forEach((button) => button.addEventListener('click', () => {
  if(window.huntmobTools?.isIos() && button.dataset.panel==='biometric'){openIosBiometrics();return;}
  const camera = button.dataset.panel === 'camera';
  document.querySelector('#fixtureEyebrow').textContent = camera ? 'CÂMERA DO APP' : 'SENSOR VIRTUAL';
  document.querySelector('#fixtureTitle').textContent = camera ? 'Câmera do app · biometria facial' : 'Digital do Android';
  document.querySelector('#deviceBiometric').hidden = camera;
  document.querySelector('#faceRecognition').hidden = !camera;
  dialog.showModal();
  if(!camera)window.huntmobBiometrics?.refresh();
  else refreshCameraSource();
}));

let cameraSourceBusy = false;
async function refreshCameraSource() {
  const status = document.querySelector('#cameraSourceStatus');
  const useHost = document.querySelector('#useHostWebcam');
  const useEmulated = document.querySelector('#useEmulatedCamera');
  if (devicePlatform !== 'android' || !activeLab.id) {
    status.textContent = 'Selecione o Android principal deste laboratório.';
    useHost.disabled = true; useEmulated.disabled = true;
    return;
  }
  const labId = activeLab.id;
  status.textContent = 'Verificando webcam do worker nativo…';
  try {
    const result = await deviceAction('front-camera-status', {lab_id: labId});
    if (labId !== activeLab.id || !dialog.open || document.querySelector('#faceRecognition').hidden) return;
    status.textContent = result.applied ? 'Webcam selecionada no boot do Android. Abra o segundo fator no app e confira o vídeo e o resultado nele.'
      : result.configured ? 'Webcam selecionada; reinício ainda não confirmado. Tente aplicar novamente.'
      : result.available ? 'Webcam detectada no worker. Ative para oferecê-la à câmera frontal do app.' : result.reason;
    status.className = 'face-status' + (result.applied ? ' ready' : '');
    useHost.disabled = cameraSourceBusy || !result.available || result.applied;
    useEmulated.disabled = cameraSourceBusy || !result.configured;
  } catch (error) {
    status.textContent = error.message;
    status.className = 'face-status error';
    useHost.disabled = true; useEmulated.disabled = true;
  }
}
async function setCameraSource(useWebcam) {
  if (cameraSourceBusy || !activeLab.id || devicePlatform !== 'android') return;
  const labId = activeLab.id;
  cameraSourceBusy = true;
  const status = document.querySelector('#cameraSourceStatus');
  document.querySelector('#useHostWebcam').disabled = true;
  document.querySelector('#useEmulatedCamera').disabled = true;
  status.textContent = 'Reiniciando o Android atual para trocar a câmera frontal…';
  try {
    const result = await deviceAction('front-camera-source', {lab_id: labId, use_webcam: useWebcam});
    if (labId !== activeLab.id) return;
    stopDeviceScreen();
    await loadRuntime();
    status.textContent = result.message + ' O resultado do segundo fator precisa ser confirmado no app.';
    status.className = 'face-status ready';
    notify(result.message);
  } catch (error) {
    status.textContent = error.message;
    status.className = 'face-status error';
  } finally {
    cameraSourceBusy = false;
    if (status.className !== 'face-status error') await refreshCameraSource();
  }
}
document.querySelector('#useHostWebcam').addEventListener('click', () => setCameraSource(true));
document.querySelector('#useEmulatedCamera').addEventListener('click', () => setCameraSource(false));


document.querySelector('#enableCamera').addEventListener('click', async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    preview.srcObject = stream;
    preview.classList.add('active');
    await new Promise((resolve) => { preview.onloadeddata = resolve; });
    await loadFaceEngine();
    enrollFace.disabled = false;
    verifyFace.disabled = !enrolledEmbedding;
    setFaceStatus('Motor pronto · posicione um rosto diante da câmera', 'ready');
    notify('Reconhecimento local pronto');
  } catch (error) {
    setFaceStatus(`Falha: ${error.message}`, 'error');
    notify('Não foi possível iniciar o reconhecimento');
  }
});

enrollFace.addEventListener('click', async () => {
  try {
    setFaceStatus('Detectando rosto para cadastro…');
    const face = await captureFace();
    enrolledEmbedding = Array.from(face.embedding);
    verifyFace.disabled = false;
    setFaceStatus('Rosto cadastrado apenas nesta sessão', 'ready');
    notify('Embedding temporário criado');
  } catch (error) {
    setFaceStatus(error.message, 'error');
  }
});

verifyFace.addEventListener('click', async () => {
  try {
    setFaceStatus('Comparando rosto…');
    const face = await captureFace();
    const match = human.match.find(face.embedding, [enrolledEmbedding], {
      order: 2, multiplier: 25, min: 0.2, max: 0.8,
    });
    const score = Math.round(match.similarity * 1000) / 10;
    const approved = match.similarity >= 0.5;
    setFaceStatus(`${approved ? 'Reconhecido' : 'Não reconhecido'} · similaridade ${score}%`, approved ? 'ready' : 'error');
    notify(`Fixture biométrica: ${approved ? 'match' : 'no-match'}`);
  } catch (error) {
    setFaceStatus(error.message, 'error');
  }
});

dialog.addEventListener('close', () => {
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = undefined;
  enrolledEmbedding = undefined;
  preview.srcObject = null;
  preview.classList.remove('active');
  overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height);
  enrollFace.disabled = true;
  verifyFace.disabled = true;
  setFaceStatus('Motor facial inativo');
  if (dialog.returnValue && dialog.returnValue !== 'cancel') {
    notify(`Fixture registrada: ${dialog.returnValue}`);
  }
});

const scriptOptions = [...document.querySelectorAll('.script-option input')];
const selectedCount = document.querySelector('#selectedCount');
const runFrida = document.querySelector('#runFrida');
const packageId = document.querySelector('#packageId');
const fridaConsole = document.querySelector('#fridaConsole');

function validPackage(value) {
  return /^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/.test(value.trim());
}

function renderFileList(target, entries, emptyMessage, source) {
  target.replaceChildren();
  if (!entries?.length) {
    const empty = document.createElement('p');
    empty.textContent = emptyMessage;
    target.append(empty);
    return;
  }
  entries.slice(0, 1000).forEach((entry) => {
    const row = document.createElement('button');
    row.type = 'button';
    const path = typeof entry === 'string' ? entry : entry.path;
    row.textContent = typeof entry === 'string' ? entry : `${entry.path}  ·  ${entry.size} B`;
    // Abre o conteúdo do arquivo ao clicar (só quando a origem é conhecida).
    if (source) row.addEventListener('click', () => openAppFile(source, path));
    target.append(row);
  });
}

// Lê e exibe o conteúdo de UM arquivo do app (entrada do APK ou path do sandbox)
// no visor. Governado: só leitura, confinado ao package autorizado pelo worker.
async function openAppFile(source, path) {
  const pkg = packageId.value.trim();
  if (!validPackage(pkg)) { notify('Informe um package ID válido'); return; }
  const viewer = document.querySelector('#fileViewer');
  document.querySelector('#fileViewerSource').textContent = source === 'apk' ? 'ENTRADA DO APK' : 'SANDBOX';
  document.querySelector('#fileViewerPath').textContent = path;
  document.querySelector('#fileViewerMeta').textContent = 'Lendo…';
  document.querySelector('#fileViewerContent').textContent = '';
  if (viewer.showModal && !viewer.open) viewer.showModal();
  try {
    const query = `/api/device/file?package=${encodeURIComponent(pkg)}&source=${encodeURIComponent(source)}&path=${encodeURIComponent(path)}`;
    const payload = await fetchJsonOk(query, { cache: 'no-store' }, 'file API');
    document.querySelector('#fileViewerMeta').textContent =
      `${payload.size} B${payload.truncated ? ' · truncado' : ''}${payload.binary ? ' · binário' : ''}`;
    document.querySelector('#fileViewerContent').textContent = payload.binary
      ? `Conteúdo binário. Preview hex (1 KB):\n\n${(payload.preview.match(/../g) || []).join(' ')}`
      : payload.content;
  } catch (error) {
    document.querySelector('#fileViewerMeta').textContent = error.message;
  }
}
document.querySelector('#fileViewerClose')?.addEventListener('click', () => document.querySelector('#fileViewer').close());

async function loadAppFiles() {
  const selectedPackage = packageId.value.trim();
  if (!validPackage(selectedPackage)) {
    notify('Informe um package ID válido');
    return;
  }
  document.querySelector('#filesPackage').textContent = selectedPackage;
  document.querySelector('#sandboxRoot').textContent = `/data/user/0/${selectedPackage} · alias /data/data/${selectedPackage}`;
  try {
    const payload = await fetchJsonOk(`/api/device/files?package=${encodeURIComponent(selectedPackage)}`, { cache: 'no-store' }, 'files API');
    renderFileList(document.querySelector('#apkFiles'), payload.apk.entries, 'APK sem entradas legíveis.', 'apk');
    renderFileList(document.querySelector('#sandboxFiles'), payload.sandbox.entries, payload.sandbox.reason || 'Sandbox vazio.', 'sandbox');
    notify(`${payload.apk.entries.length} entradas do APK · ${payload.sandbox.entries.length} caminhos no sandbox`);
  } catch (error) {
    renderFileList(document.querySelector('#apkFiles'), [], error.message);
    renderFileList(document.querySelector('#sandboxFiles'), [], error.message);
    notify(error.message);
  }
}

document.querySelector('#refreshFiles').addEventListener('click', loadAppFiles);

let currentSelectedPackage = "";
let targetBindingBusy = false;
async function selectApp(packageName, revalidate=false) {
  if(targetBindingBusy)return false;
  const expectedLab=activeLab.id;
  if(currentSelectedPackage!==packageName || revalidate){
    targetBindingBusy=true;refreshFridaSelection();
    document.querySelector('#targetAppState').textContent='Validando app instalado…';
    try{
      const result=await deviceAction('select-target',{package_id:packageName});
      if(devicePlatform!=='android'||activeLab.id!==expectedLab||result.lab?.id!==expectedLab)return false;
      activeLab=result.lab;
    }catch(error){document.querySelector('#targetAppState').textContent=error.message;notify(error.message);return false;}
    finally{targetBindingBusy=false;refreshFridaSelection();}
  }
  const changed = currentSelectedPackage !== packageName;
  currentSelectedPackage = packageName;
  if(changed)window.dispatchEvent(new Event('huntmob:reverse-reset'));
  document.querySelector('#targetAppState').textContent = 'App alvo selecionado';
  packageId.value = packageName;
  document.querySelector('#reversePackage').textContent = packageName;
  if (!document.querySelector('#prepareReverse')) document.querySelector('#reverseOutput').innerHTML = reverseInitialHtml;
  document.querySelector('#prepareReverse').disabled = !analysisReady;
  document.querySelector('#reverseHash').textContent = activeLab.apk_sha256 ? `SHA256 · ${activeLab.apk_sha256.slice(0,8)}…${activeLab.apk_sha256.slice(-4)}` : 'SHA256 pendente';
  refreshFridaSelection();
  if (changed || !reverseAnalysis) await restoreReverseWorkspace(packageName);
  window.huntmobDastApps?.sync();
  return true;
}

async function loadInstalledApps() {
  const target = document.querySelector('#installedApps');
  target.innerHTML = '<p>Consultando device…</p>';
  try {
    const payload = await fetchJsonOk('/api/device/apps', { cache: 'no-store' }, 'apps API');
    if (reverseAnalysis?.package_id === currentSelectedPackage) { renderReverseTree(reverseAnalysis); return payload.apps; }
    target.replaceChildren();
    if (!payload.apps.length) {
      target.innerHTML = '<p>Nenhum app de terceiro instalado.</p>';
      notify('Nenhum app de terceiro instalado no device');
      return [];
    }
    const mainApps = activeLab.package_id ? payload.apps.filter(app => app.package_id === activeLab.package_id) : [];
    if (mainApps.length) {
      await selectApp(activeLab.package_id);
      const selected = document.createElement('strong');
      selected.className = 'target-package';
      selected.textContent = activeLab.package_id;
      target.append(selected);
    }
    const advanced = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `Outros pacotes · avançado (${payload.apps.length - mainApps.length})`;
    advanced.append(summary);
    target.append(advanced);
    payload.apps.filter(app => !mainApps.includes(app)).forEach((app) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.textContent = app.package_id;
      row.addEventListener('click', () => selectApp(app.package_id,true));
      advanced.append(row);
    });
    notify(`${payload.apps.length} app(s) instalado(s) detectado(s)`);
    return payload.apps;
  } catch (error) {
    const message=document.createElement('p');message.textContent=error.message;target.replaceChildren(message);
    notify(error.message);
    return [];
  }
}

document.querySelector('#refreshApps').addEventListener('click', loadInstalledApps);
let reversePreparationBusy = false;
async function prepareReverseWorkspace(selectedPackage) {
  if (!validPackage(selectedPackage)) throw new Error('Selecione um package válido.');
  if (reversePreparationBusy) throw new Error('O APK já está sendo preparado.');
  reversePreparationBusy = true;
  const output = document.querySelector('#reverseOutput');
  output.innerHTML = '<strong>Extraindo APK e analisando aplicativo…</strong><p>Isso pode levar alguns minutos.</p>';
  try {
    const payload = await authorizedPost('/api/reverse', { package_id: selectedPackage });
    renderReverseWorkspace(payload);
    notify(payload.status === 'partial' ? 'Análise parcial disponível para revisão' : `Decompilação criada para ${selectedPackage}`);
    return payload;
  } catch (error) {
    output.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = 'Análise não concluída';
    const message = document.createElement('p');
    message.textContent = error.message;
    const retry = document.createElement('button');
    retry.id = 'prepareReverse';
    retry.className = 'primary';
    retry.textContent = 'Tentar novamente';
    output.append(title, message, retry);
    if (error.payload?.sha256) document.querySelector('#reverseHash').textContent = `SHA256 · ${error.payload.sha256.slice(0, 8)}…`;
    document.querySelector('#fileName').textContent = 'Análise não concluída';
    notify(error.message);
    throw error;
  } finally {
    reversePreparationBusy = false;
  }
}
document.querySelector('#reverseOutput').addEventListener('click', async event => {
  if (!event.target.closest('#prepareReverse')) return;
  try { await prepareReverseWorkspace(packageId.value.trim()); }
  catch { /* The workspace panel already shows the error and retry action. */ }
});

const quickReaPackage = document.querySelector('#quickReaPackage');
const quickReaStart = document.querySelector('#quickReaStart');
const quickReaStatus = document.querySelector('#quickReaStatus');
let quickReaBusy = false;
function quickReaAllowed() {
  return devicePlatform === 'android' && runtimeDevice?.state === 'on' && !!activeLab.id && !window.huntmobTools?.extra();
}
async function refreshQuickReaApps() {
  quickReaStart.disabled = true;
  quickReaPackage.disabled = true;
  if (!quickReaAllowed()) {
    quickReaPackage.replaceChildren(new Option('Selecione o Android principal', ''));
    quickReaStatus.textContent = 'REA disponível para apps instalados no Android principal.';
    return;
  }
  const labId = activeLab.id;
  quickReaStatus.textContent = 'Consultando apps instalados…';
  try {
    const data = await fetchJsonOk('/api/device/apps', {cache: 'no-store', signal: AbortSignal.timeout(10000)}, 'Não foi possível listar os apps.');
    if (labId !== activeLab.id || !quickReaAllowed()) return;
    const apps = [...new Set((data.apps || []).map(app => app.package_id).filter(validPackage))];
    quickReaPackage.replaceChildren(new Option('Escolha um APK instalado', ''));
    apps.forEach(name => quickReaPackage.add(new Option(name, name)));
    quickReaPackage.value = apps.includes(currentSelectedPackage) ? currentSelectedPackage : apps.includes(activeLab.package_id) ? activeLab.package_id : '';
    quickReaPackage.disabled = !apps.length;
    quickReaStart.disabled = quickReaBusy || !quickReaPackage.value || !analysisReady;
    quickReaStatus.textContent = apps.length ? `${apps.length} app(s) instalado(s). Selecione o APK para análise estática.` : 'Nenhum app de terceiro instalado no Android principal.';
  } catch (error) {
    quickReaStatus.textContent = error.message;
  }
}
quickReaPackage.addEventListener('change', () => { quickReaStart.disabled = quickReaBusy || !quickReaPackage.value || !analysisReady; });
document.querySelector('#quickReaRefresh').addEventListener('click', refreshQuickReaApps);
document.querySelector('[data-tab="device-tools"]').addEventListener('click', refreshQuickReaApps);
// Static-RE orchestration for the active lab's package: verify REA, bind the app,
// prepare or restore the workspace, start the inspection and open the Reverse tab.
// Shared by the device-tools quick action and the sidebar per-lab action.
async function huntmobStartReaForPackage(selectedPackage, onStatus) {
  const status = typeof onStatus === 'function' ? onStatus : () => {};
  const labId = activeLab.id;
  status('Verificando REA no worker…');
  const readiness = await fetchJson('/api/reverse/engines', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
  if (!readiness.rea_ready) throw new Error(readiness.rea_reason || 'REA indisponível neste worker.');
  if (labId !== activeLab.id) throw new Error('O laboratório selecionado mudou.');
  status('Validando app e preparando APK…');
  if (!await selectApp(selectedPackage, true)) throw new Error('O app não pôde ser vinculado ao laboratório.');
  if (labId !== activeLab.id || currentSelectedPackage !== selectedPackage || activeLab.package_id !== selectedPackage) throw new Error('O app selecionado mudou.');
  const targetResponse = await fetch('/api/reverse/target?' + new URLSearchParams({workspace: labId}), {cache: 'no-store'});
  const target = await targetResponse.json();
  if (!targetResponse.ok) throw new Error(target.reason || 'Contexto REA indisponível.');
  if (target.prepared) {
    await restoreReverseWorkspace(selectedPackage, true);
  } else {
    status('Extraindo e preparando o APK para REA…');
    await prepareReverseWorkspace(selectedPackage);
  }
  if (labId !== activeLab.id || currentSelectedPackage !== selectedPackage) throw new Error('O app selecionado mudou.');
  if (!window.huntmobReaInspectPackage) throw new Error('Módulo REA ainda não carregado.');
  status('Iniciando inspeção estática REA…');
  await window.huntmobReaInspectPackage();
  document.querySelector('[data-tab="reverse"]').click();
}
window.huntmobStartReaForPackage = huntmobStartReaForPackage;
quickReaStart.addEventListener('click', async () => {
  if (quickReaBusy || !quickReaAllowed() || !validPackage(quickReaPackage.value)) return;
  quickReaBusy = true;
  quickReaStart.disabled = true;
  const selectedPackage = quickReaPackage.value;
  try {
    await huntmobStartReaForPackage(selectedPackage, message => { quickReaStatus.textContent = message; });
    quickReaStatus.textContent = 'Inspeção REA iniciada. Acompanhe o resultado em Reverse.';
  } catch (error) {
    quickReaStatus.textContent = error.message;
    notify(error.message);
  } finally {
    quickReaBusy = false;
    quickReaStart.disabled = !quickReaAllowed() || !quickReaPackage.value || !analysisReady;
  }
});
document.querySelector('#quickTlsObserve').addEventListener('click', () => {
  const status = document.querySelector('#quickTlsStatus');
  if (!quickReaAllowed()) { status.textContent = 'Selecione o Android principal online.'; return; }
  const observer = document.querySelector('.script-option input[value="tls-observe"]');
  if (!observer || observer.disabled) { status.textContent = 'Observador TLS indisponível neste worker.'; return; }
  observer.checked = true;
  refreshFridaSelection();
  document.querySelector('[data-tab="frida"]').click();
  status.textContent = 'Observador TLS selecionado. Inicie a sessão Frida para registrar chamadas de trust e pinning; mTLS precisa de validação separada.';
});

function refreshFridaSelection() {
  const selected = scriptOptions.filter((item) => item.checked);
  selectedCount.textContent = `${selected.length} selecionado${selected.length === 1 ? '' : 's'}`;
  runFrida.disabled = targetBindingBusy || selected.length === 0 || !validPackage(packageId.value);
}

scriptOptions.forEach((option) => option.addEventListener('change', refreshFridaSelection));
packageId.addEventListener('input', refreshFridaSelection);
document.querySelector('#scriptSearch').addEventListener('input', (event) => {
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll('.script-option').forEach((row) => {
    row.hidden = query && !row.textContent.toLowerCase().includes(query);
  });
});
document.querySelector('#detectApps').addEventListener('click', loadInstalledApps);
let dynamicBusy = false;
let dynamicError = '';
let dynamicPollBusy = false;
let dynamicSessionLab = '', dynamicSessionActive = false;
let dastAppSignature = '';
let dastInventory, dastDeviceId='primary';
function dastTarget(){
  const child=dastDeviceId!=='primary'&&dastInventory?.workspace_id===activeLab.id?dastInventory.devices.find(d=>d.id===dastDeviceId):null;
  return child?{...child,available:devicePlatform==='android'&&child.online===true}: {...activeLab,available:devicePlatform==='android'&&runtimeDevice?.state==='on'};
}
function dastQuery(){return dastDeviceId==='primary'?'':'?'+new URLSearchParams({workspace:activeLab.id,device:dastDeviceId});}
function dastPayload(){return dastDeviceId==='primary'?{}:{workspace_id:activeLab.id,device_id:dastDeviceId};}
let dastProgressScope='',dastProgressData={},dastProgressReport,dastProgressOperation,dastProgressError='';
function updateDastProgress(data){
  const scope=dastTarget().id||'';
  if(dastProgressScope!==scope){dastProgressScope=scope;dastProgressData={};dastProgressReport=dastProgressOperation=undefined;dastProgressError='';}
  if(data&&(!data.receipt||data.receipt.lab_id===scope)){dastProgressData=data;dastProgressError='';}
  const view=window.huntmobDastProgress.present({snapshot:dastProgressData,report:dastProgressReport,operation:dastProgressOperation?.scope===scope?dastProgressOperation:undefined,error:dastProgressError});
  const panel=document.querySelector('#dastProgress'),bar=document.querySelector('#dastProgressBar');panel.dataset.state=view.kind;
  for(const [id,value]of [['dastProgressTitle',view.title],['dastProgressPercent',view.percentage],['dastElapsedLabel',view.timeLabel],['dastElapsed',view.time],['dastRemainingLabel',view.remainingLabel],['dastRemaining',view.remaining],['dastProgressDetail',view.detail]]){const el=document.querySelector('#'+id);if(el.textContent!==value)el.textContent=value;}
  bar.dataset.indeterminate=String(view.indeterminate);bar.setAttribute('aria-label',view.indeterminate?'Progresso da operação':view.kind==='complete'?'Conclusão do relatório':'Tempo da janela de coleta');bar.setAttribute('aria-valuetext',view.percentage||view.title);
  if(view.value===null)bar.removeAttribute('aria-valuenow');else bar.setAttribute('aria-valuenow',String(view.value));
  bar.firstElementChild.style.width=view.indeterminate?'35%':(view.value??0)+'%';
  panel.querySelectorAll('[data-step]').forEach((step,i)=>{step.dataset.state=view.steps[i];if(view.steps[i]==='current')step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');});
}
everyVisible(()=>{if(document.querySelector('#tab-dast').classList.contains('active'))updateDastProgress();},1000);
function clearDastView(){
  dynamicSessionLab='';dynamicSessionActive=false;nativeReportJob='';dynamicError='';dastConnection={};
  dastProgressData={};dastProgressReport=dastProgressOperation=undefined;dastProgressError='';updateDastProgress();
  for(const id of ['nativeCoverage','nativeCandidates','nativeObservations','nativeLimitations'])document.querySelector('#'+id).replaceChildren();
  document.querySelector('#nativeMetrics').hidden=true;
  document.querySelector('#nativeReportStatus').textContent='Nenhuma análise carregada para este aparelho.';
  document.querySelector('#nativeReportJson').hidden=document.querySelector('#nativeReportHtml').hidden=true;
  document.querySelector('#dastEvents').textContent='';document.querySelector('#dastMetrics').textContent='Sem eventos neste aparelho';
  for(const [id,path] of [['exportDast','export'],['nativeReportJson','report.json'],['nativeReportHtml','report.html']])document.querySelector('#'+id).href='/api/dynamic/'+path+dastQuery();
  document.querySelector('#deepDastGates').replaceChildren();document.querySelector('#deepDastResult').hidden=true;
  document.querySelector('#deepAnalyzeDast').disabled=true;document.querySelector('#prepareDeepRea').disabled=true;
  document.querySelector('#deepEngagementForm').hidden=true;document.querySelector('#deepDastStatus').textContent='Verificando a correlação deste aparelho…';
}
window.huntmobDastDevices={
  sync(data){
    const before=dastTarget().id;
    if(data?.workspace_id)dastInventory=data;
    if(dastInventory?.workspace_id!==activeLab.id){dastInventory=undefined;dastDeviceId='primary';}
    const select=document.querySelector('#dastDeviceSelect'),items=[['primary','Principal · API '+(activeLab.android_api||'')+' · '+(activeLab.root_mode==='stock'?'sem root':'com root')],...(dastInventory?.devices||[]).filter(d=>d.platform==='android'&&d.link?.kind==='root-companion').map(d=>[d.id,'Companheiro · API '+d.android_api+' · com root'+(d.online?'':' · desligado')])];
    if(!items.some(([id])=>id===dastDeviceId))dastDeviceId='primary';
    if(JSON.stringify(items)!==select.dataset.items){select.dataset.items=JSON.stringify(items);select.replaceChildren(...items.map(([id,label])=>new Option(label,id)));}
    select.value=dastDeviceId;select.disabled=dynamicBusy;
    document.querySelector('#dastDeviceNote').textContent=dastDeviceId==='primary'?'Sessão e evidências vinculadas ao Android principal.':'Sessão e relatório próprios deste companheiro. A correlação usa REA do mesmo SHA256; tráfego do proxy principal não é atribuído a este aparelho.';
    if(before!==dastTarget().id)clearDastView();
    window.huntmobDastApps?.sync();
  },
  async select(id){
    if(dynamicBusy)return;
    dastDeviceId=id===activeLab.id?'primary':id;this.sync();clearDastView();
    document.querySelector('[data-tab="dast"]').click();await refreshDynamic();await loadNativeReport();await refreshDeepDast();
  }
};
document.querySelector('#dastDeviceSelect').addEventListener('change',event=>window.huntmobDastDevices.select(event.target.value));
let dastConnection={};
const dastConnectionKey=()=>JSON.stringify([devicePlatform,activeLab.id,dastTarget().id,dastTarget().package_id,dastTarget().apk_sha256,dastTarget().root_mode]);
const currentDastConnection=()=>dastConnection.key===dastConnectionKey()?dastConnection:{};
async function refreshDastConnection(force=false) {
  const target=dastTarget();
  if(!target.available||!target.package_id||!target.apk_sha256||dynamicBusy||targetBindingBusy||dynamicSessionActive)return;
  const key=dastConnectionKey(),existing=currentDastConnection();
  if(existing.loading||(!force&&existing.checked))return;
  dastConnection={key,loading:true,checked:false,ready:false};dastAppPicker.sync();
  try {
    const response=await fetch('/api/dynamic/readiness'+dastQuery(),{cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error('Verificação Frida indisponível. Confira a conexão do worker.');
    const data=await response.json();
    if(key!==dastConnectionKey()||dastConnection.key!==key)return;
    if(data.lab_id!==target.id||data.package_id!==target.package_id||data.apk_sha256!==target.apk_sha256)throw new Error('O contexto do app mudou. Clique em Verificar Frida novamente.');
    dastConnection={key,checked:true,ready:data.ready===true,error_code:data.error_code,reason:data.reason};
  } catch(error) {
    if(key===dastConnectionKey()&&dastConnection.key===key)dastConnection={key,checked:true,ready:false,error_code:'readiness_unavailable',reason:error.name==='TimeoutError'?'A verificação Frida demorou. Tente novamente.':error instanceof SyntaxError?'Resposta do worker indisponível. Verifique a conexão novamente.':error.message};
  } finally {
    if(dastConnection.key===key){dastConnection.loading=false;window.huntmobDastApps?.sync();}
  }
}
function renderDastTarget(view) {
  document.querySelector('#dastDeviceSelect').disabled=dynamicBusy||targetBindingBusy;
  const select=document.querySelector('#dastAppSelect'),status=document.querySelector('#dastAppStatus');
  const signature=JSON.stringify([view.scope,view.apps,view.packageId,view.active]);
  if(signature!==dastAppSignature){
    dastAppSignature=signature;
    select.replaceChildren(new Option('Selecione um app instalado…',''));
    select.options[0].disabled=true;
    const names=[...view.apps];if(view.packageId&&!names.includes(view.packageId))names.unshift(view.packageId);
    for(const name of names){const option=new Option(name,name);option.disabled=name!==view.packageId&&(view.active||!!view.packageId);select.add(option);}
  }
  select.value=view.binding||view.packageId||'';
  select.disabled=view.disabled&&!view.browseOnly;
  const refresh=document.querySelector('#refreshDastApps');
  refresh.disabled=view.refreshDisabled;refresh.textContent=view.loading?'Atualizando…':'Atualizar apps';
  status.dataset.error=String(!!view.error);
  status.textContent=!view.available?'Selecione um Android online para listar seus apps.':view.binding?'Identificando o APK selecionado…':view.loading?'Buscando apps instalados no Android…':view.error?view.error:view.active?`${view.apps.length} app(s) listado(s). Sessão em andamento; você pode consultar a lista. Encerre antes de trocar o aplicativo.`:view.checking?'Verificando a sessão DAST…':!view.loaded?'Clique em Atualizar apps para carregar a lista.':!view.apps.length?'Nenhum app de terceiro instalado. Instale o app no Android e atualize a lista.':view.packageId&&!view.apps.includes(view.packageId)?'O app vinculado não está instalado neste Android. Verifique a instalação e atualize a lista.':view.packageId?'App selecionado para este laboratório. Para analisar outro app, crie um novo lab.':`${view.apps.length} app(s) instalado(s). Escolha o aplicativo para DAST.`;
  document.querySelector('#dastRuntimeNote').hidden=!view.available||view.rootMode!=='stock';
  const connection=currentDastConnection(),connectionStatus=document.querySelector('#dastConnectionStatus'),check=document.querySelector('#checkDastConnection');
  check.disabled=!view.available||!view.packageId||!!view.binding||!!view.busy||!!view.active||!!connection.loading;
  check.textContent=connection.loading?'Verificando Frida…':'Verificar Frida';
  connectionStatus.textContent=!view.available?'Selecione um Android online para verificar o Frida.':!view.packageId?'Selecione o app para verificar a conexão de instrumentação.':connection.loading?'Verificando os requisitos do Frida neste Android…':connection.reason||'Clique em Verificar Frida antes de iniciar a sessão.';
  connectionStatus.dataset.error=String(!!view.available&&!!connection.checked&&!connection.ready);connectionStatus.dataset.ready=String(!!view.available&&connection.ready===true);
  renderDastActions(view);
}
function renderDastActions(view){
  const snapshot=dastProgressScope===view.labId?dastProgressData:{};
  const actions=window.huntmobDastProgress.actions({active:view.active,busy:view.busy,available:view.available,identified:!!view.packageId&&!!view.sha256,canStart:view.canStart,hasReceipt:!!snapshot.receipt});
  const start=document.querySelector('#startDast'),stop=document.querySelector('#stopDast'),analyze=document.querySelector('#analyzeDast'),exportLink=document.querySelector('#exportDast');
  start.hidden=!actions.showStart;start.disabled=!actions.startEnabled;
  stop.hidden=!actions.showStop;stop.disabled=!actions.stopEnabled;stop.className=actions.showStop?'primary':'outline';
  document.querySelector('#captureDast').disabled=!actions.captureEnabled;
  analyze.disabled=!actions.analyzeEnabled;analyze.textContent=actions.analyzeLabel;
  exportLink.setAttribute('aria-disabled',String(!actions.exportEnabled));exportLink.tabIndex=actions.exportEnabled?0:-1;
  if(actions.exportEnabled)exportLink.href='/api/dynamic/export'+dastQuery();else exportLink.removeAttribute('href');
  const help=document.querySelector('#dastActionHelp');if(help.textContent!==actions.help)help.textContent=actions.help;
}
const dastAppPicker=window.huntmobDastTarget.create({
  context:()=>({labId:dastTarget().id,packageId:dastTarget().package_id,sha256:dastTarget().apk_sha256,rootMode:dastTarget().root_mode,connectionReady:currentDastConnection().ready===true,
    available:!!dastTarget().available,
    checking:dynamicSessionLab!==dastTarget().id,busy:dynamicBusy||targetBindingBusy||dynamicSessionLab!==dastTarget().id,active:dynamicSessionLab===dastTarget().id&&dynamicSessionActive}),
  list:async()=>{
    const data=await fetchJson('/api/dynamic/apps'+dastQuery(),{cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!data.ok||!Array.isArray(data.apps))throw new Error(data.reason||'Não foi possível listar os apps. Clique em Atualizar apps para tentar novamente.');
    return data.apps.map(app=>app.package_id);
  },
  bind:async selected=>{
    if(dastDeviceId!=='primary'){if(selected!==dastTarget().package_id||!dastTarget().apk_sha256)throw new Error('Sincronize o app selecionado no par antes de iniciar.');return true;}
    if(!await selectApp(selected,true))throw new Error(document.querySelector('#targetAppState').textContent||'Não foi possível selecionar o app.');
    return true;
  },onChange:renderDastTarget
});
window.huntmobDastApps={
  load:()=>dastAppPicker.load(),
  sync(){if(!dastTarget().available)dastConnection={};const view=dastAppPicker.sync();if(document.querySelector('#tab-dast').classList.contains('active')&&view.available&&!view.busy){if(!view.attempted)void dastAppPicker.load();if(view.packageId&&!view.binding&&!view.active)void refreshDastConnection();}}
};
document.querySelector('#checkDastConnection').addEventListener('click',()=>refreshDastConnection(true));
document.querySelector('#refreshDastApps').addEventListener('click',()=>dastAppPicker.load());
document.querySelector('#dastAppSelect').addEventListener('change',async event=>{
  if(await dastAppPicker.choose(event.target.value)){await refreshDynamic();await refreshDeepDast();}
});
const observerIds = ['tls-observe', 'biometric-monitor', 'root-detection-observe', 'webview-observe', 'crypto-observe', 'file-observe'];
async function refreshDynamic() {
  if (dynamicPollBusy || devicePlatform!=='android') return;
  dynamicPollBusy = true;
  const requestedLab=dastTarget().id;
  try {
    const response = await fetch('/api/dynamic/status'+dastQuery(), {cache: 'no-store'});
    if (!response.ok) throw new Error('Worker Frida indisponível');
    const data = await response.json();
    if(devicePlatform!=='android'||dastTarget().id!==requestedLab)return;
    const active = ['running', 'starting'].includes(data.state);
    dynamicSessionLab=requestedLab;dynamicSessionActive=active;updateDastProgress(data);
    const states = {idle: 'Sem sessão', running: 'Instrumentando', starting: 'Iniciando', stopped: 'Parada', failed: 'Falhou', detached: 'App desconectado', interrupted: 'Worker reiniciado'};
    document.querySelector('#dastState').textContent = states[data.state] || data.state;
    document.querySelector('#dastTarget').textContent = data.receipt ? `${data.receipt.package_id} · SHA256 ${data.receipt.apk_sha256.slice(0,12)} · Frida ${data.receipt.frida_version}` : dastTarget().package_id || 'Selecione um aplicativo';
    if (nativeReportJob && data.receipt && nativeReportJob !== data.receipt.id) document.querySelector('#nativeReportStatus').textContent = 'Relatório de uma sessão anterior. Analise a sessão atual para atualizar.';
    else if(!nativeReportJob&&active)document.querySelector('#nativeReportStatus').textContent='A coleta está em andamento. Use Gerar análise parcial para consultar os resultados já coletados.';
    const events = data.events || [];
    const lines = events.map(event => `${new Date(event.at).toLocaleTimeString('pt-BR')}  ${event.script || 'sessão'}  ${event.kind}  ${event.class_name || ''}${event.method ? '.' + event.method : ''}${event.algorithm ? ' · ' + event.algorithm : ''}`);
    document.querySelector('#dastEvents').textContent = lines.join('\n') || 'Nenhum evento nesta sessão. APIs ausentes são indicadas; não equivalem a finding.';
    document.querySelector('#fridaSessionState').textContent=active ? states[data.state] : data.receipt ? 'Última sessão · '+(states[data.state] || data.state) : 'Sem sessão';
    fridaConsole.textContent = dynamicError ? dynamicError + '\n\n' + lines.join('\n') : lines.join('\n') || states[data.state] || 'Selecione monitores e teste no app.';
    document.querySelector('#dastMetrics').textContent = `${events.length} eventos exibidos · ${events.filter(e => e.kind === 'call').length} chamadas · ${events.filter(e => e.kind === 'hook_unavailable').length} hooks ausentes`;
    document.querySelector('#stopDast').disabled = dynamicBusy || !active;
    document.querySelector('#stopFrida').disabled = dynamicBusy || !active;
    runFrida.disabled = targetBindingBusy || dynamicBusy || active || !scriptOptions.some(item => item.checked && !item.disabled) || !validPackage(packageId.value);
  } catch (error) { if(dastTarget().id===requestedLab){dynamicSessionLab='';document.querySelector('#dastState').textContent=error.message;dastProgressError=error.message;updateDastProgress();} }
  finally { dynamicPollBusy = false;window.huntmobDastApps?.sync(); }
}
async function dynamicAction(action, dast = false) {
  if (dynamicBusy || targetBindingBusy) return;
  if(dast&&action==='start'&&!dastAppPicker.state().canStart)return;
  dynamicBusy = true; dynamicError = '';
  const requestedLab=dastTarget().id;
  updateDastProgress();dastProgressError='';dastProgressOperation={scope:requestedLab,action,started:Date.now()/1000};updateDastProgress();
  document.querySelector('#analyzeDast').disabled=true;
  window.huntmobDastApps?.sync();
  document.querySelector('#dastState').textContent = 'Executando…';
  const selected = scriptOptions.filter(item => item.checked && !item.disabled).map(item => item.value);
  try {
    const result = await authorizedPost('/api/dynamic', {...dastPayload(),action, package_id: dast?dastTarget().package_id:packageId.value.trim(), mode: document.querySelector('#fridaMode').value, script_ids: dast ? observerIds : selected.length ? selected : observerIds, include_proxy: dast&&dastDeviceId==='primary'});
    if(dastTarget().id!==requestedLab)return;
    if (result.proxy && !result.proxy.ok) notify('Frida ativo; captura de rede não ficou pronta. Verifique Proxy.');
    else notify(action === 'prepare' ? 'Servidor Frida preparado' : action === 'capture' ? 'Evidência capturada' : action === 'stop' ? 'Sessão encerrada' : action==='analyze'?'Relatório de evidências atualizado':'Agente real conectado ao app');
    if (action === 'capture') loadEvidence();
    if (result.report) renderNativeReport(result.report);
    if (action === 'start') { clearReportDetails(); nativeReportJob = ''; document.querySelector('#nativeCoverage').replaceChildren(); document.querySelector('#nativeCandidates').replaceChildren(); document.querySelector('#nativeReportStatus').textContent = 'Nova sessão em andamento. Encerre e analise para atualizar o relatório.'; document.querySelector('#nativeReportJson').hidden = true; document.querySelector('#nativeReportHtml').hidden = true; }
  } catch (error) {
    if(dastTarget().id!==requestedLab)return;
    dynamicError = error.message;dastProgressError=error.message;notify(error.message);fridaConsole.textContent=error.message;
    if(action==='start')dastConnection={key:dastConnectionKey(),checked:true,ready:false,error_code:error.payload?.error_code||'connection_failed',reason:error.message};
  }
  finally { dynamicBusy=false;if(dastProgressOperation?.scope===requestedLab)dastProgressOperation=undefined;document.querySelector('#analyzeDast').disabled=false;updateDastProgress();await refreshDynamic(); }
}
runFrida.addEventListener('click', () => dynamicAction('start'));
document.querySelector('#prepareFrida').addEventListener('click', () => dynamicAction('prepare'));
document.querySelector('#stopFrida').addEventListener('click', () => dynamicAction('stop'));
document.querySelector('#startDast').addEventListener('click', () => dynamicAction('start', true));
document.querySelector('#stopDast').addEventListener('click', () => dynamicAction('stop',true));
document.querySelector('#captureDast').addEventListener('click', () => dynamicAction('capture',true));
let nativeReportJob = '';
async function loadNativeReport() {
  try {
    const response = await fetch('/api/dynamic/report'+dastQuery(), {cache:'no-store'});
    if (!response.ok) return;
    const report = await response.json(); if (report.lab_id === dastTarget().id) renderNativeReport(report);
  } catch (_) {}
}
function renderNativeReport(report) {
  if(report.lab_id!==dastTarget().id)return;
  updateDastProgress();dastProgressReport=report;updateDastProgress();syncEngagementStepper();
  nativeReportJob = report.job_id;
  const summary = report.summary;
  document.querySelector('#nativeReportStatus').textContent = `${['running','starting'].includes(report.session_state)?'Análise parcial · coleta em andamento':'Análise da sessão'} · ${summary.events} eventos · ${summary.network_requests} requisições · ${summary.candidates} candidato(s) para revisão · gerado ${new Date(report.generated_at).toLocaleString('pt-BR')}`;
  const coverage = document.querySelector('#nativeCoverage'); coverage.replaceChildren();
  const states = {observed:'Observado',ready_not_exercised:'Não exercitado',unavailable:'API indisponível',not_selected:'Não selecionado',no_evidence:'Sem evidência'};
  const metrics = document.querySelector('#nativeMetrics'); metrics.replaceChildren(); metrics.hidden = false;
  [[summary.candidates, 'Para revisão'], [summary.observed_monitors, 'Áreas observadas'], [summary.network_requests, 'Requisições'], [summary.events, 'Eventos']].forEach(([value,label]) => {
    const cell = document.createElement('div'); const number = document.createElement('strong'); number.textContent = value; const caption = document.createElement('span'); caption.textContent = label; cell.append(number,caption); metrics.append(cell);
  });
  (report.checks || report.coverage).forEach(item => {
    const row = document.createElement('details'); row.className = 'native-coverage-row'; row.dataset.state = item.state;
    const heading = document.createElement('summary'); const title = document.createElement('strong'); title.textContent = item.title;
    const status = document.createElement('span'); status.textContent = `${states[item.state] || item.state} · ${item.calls} chamada(s)`;
    heading.append(title,status); row.append(heading);
    const evaluated = document.createElement('p'); evaluated.textContent = item.evaluated || 'Observação das APIs selecionadas nesta sessão.';
    const next = document.createElement('p'); next.textContent = item.next_step || 'Exercite este fluxo para coletar evidências. Ausência de chamada não indica segurança.';
    const hooks = document.createElement('small'); hooks.textContent = `${item.hooks_ready} hook(s) pronto(s) · ${item.hooks_unavailable} indisponível(is)`;
    row.append(evaluated,next,hooks);
    (item.methods || []).forEach(method => { const line = document.createElement('p'); line.className = 'observed-method'; line.textContent = `${method.class_name}.${method.method} · ${method.calls} chamada(s)`; row.append(line); });
    coverage.append(row);
  });
  const candidates = document.querySelector('#nativeCandidates'); candidates.replaceChildren();
  if (!report.candidates.length) {
    const empty = document.createElement('p'); empty.textContent = 'Nenhum candidato nas evidências analisadas. Monitores não exercitados continuam sem validação.'; candidates.append(empty);
  }
  const severities = {high:'Alta',medium:'Média',low:'Baixa',critical:'Crítica'};
  report.candidates.forEach((item,index) => {
    const card = document.createElement('details'); card.open = index === 0;
    const title = document.createElement('summary'); const severity = document.createElement('span'); severity.className = 'severity severity-' + (['high','medium','low','critical'].includes(item.severity) ? item.severity : 'low'); severity.textContent = severities[item.severity] || item.severity;
    const name = document.createElement('strong'); name.textContent = item.title; title.append(severity,name);
    const classification = document.createElement('p'); classification.className = 'candidate-meta'; classification.textContent = `${item.cwe} · Evidência observada · Impacto precisa validar`;
    const description = document.createElement('p'); description.textContent = item.description;
    const remediation = document.createElement('p'); remediation.textContent = 'Remediação: ' + item.remediation;
    const evidenceBlock = document.createElement('details'); const evidenceTitle = document.createElement('summary'); evidenceTitle.textContent = `${item.evidence.length} referência(s) de evidência`;
    const evidence = document.createElement('pre'); evidence.textContent = JSON.stringify(item.evidence,null,2); evidenceBlock.append(evidenceTitle,evidence);
    card.append(title,classification,description,remediation,evidenceBlock); candidates.append(card);
  });
  const observations = document.querySelector('#nativeObservations'); observations.replaceChildren();
  (report.observations || []).forEach(item => {
    const row = document.createElement('details'); const title = document.createElement('summary'); title.textContent = `${item.title} · ${item.count || 0} registro(s)`;
    const meaning = document.createElement('p'); meaning.textContent = item.meaning || item.algorithm || 'Observação de execução; não classificada como vulnerabilidade.';
    const evidence = document.createElement('pre'); evidence.textContent = JSON.stringify(item.evidence || [],null,2); row.append(title,meaning,evidence); observations.append(row);
  });
  if (!report.observations?.length) { const empty = document.createElement('p'); empty.textContent = 'Nenhuma observação adicional nesta captura.'; observations.append(empty); }
  const network = report.network_summary;
  if (network) { const row = document.createElement('p'); row.textContent = `Rede: ${network.http} HTTP · ${network.https} HTTPS · ${network.http_errors} erros HTTP · ${network.connection_failures} falhas de conexão. Hosts: ${network.hosts.join(', ') || 'nenhum'}`; observations.prepend(row); }
  const limits = document.querySelector('#nativeLimitations'); limits.replaceChildren();
  const manual = document.querySelector('#nativeManualChecks'); manual.replaceChildren();
  (report.manual_checks || []).forEach(item => { const title = document.createElement('strong'); title.textContent = item.title + ' · Não avaliado automaticamente'; const next = document.createElement('p'); next.textContent = item.next_step; manual.append(title,next); });
  report.limitations.forEach(text => { const li = document.createElement('li'); li.textContent = text; limits.append(li); });
  document.querySelector('#nativeReportJson').hidden = false;
  document.querySelector('#nativeReportHtml').hidden = false;
}
document.querySelector('#analyzeDast').addEventListener('click',()=>dynamicAction('analyze',true));
loadNativeReport();
let deepDastPolling = false;
let deepDastBusy = false;
function renderDeepDast(data) {
  const gates = document.querySelector('#deepDastGates'); gates.replaceChildren();
  (data.gates || []).forEach(item => {
    const row = document.createElement('div'); row.dataset.state = item.passed ? 'passed' : 'blocked';
    const marker = document.createElement('span'); marker.textContent = item.passed ? 'PASS' : 'BLOCK';
    const copy = document.createElement('div'); const title = document.createElement('strong'); title.textContent = item.id;
    const detail = document.createElement('small'); detail.textContent = item.detail; copy.append(title,detail); row.append(marker,copy); gates.append(row);
  });
  const button = document.querySelector('#deepAnalyzeDast');
  const status = document.querySelector('#deepDastStatus');
  const job = data.job;
  button.disabled = deepDastBusy || !data.ready || job?.state === 'running';
  button.textContent = job?.state === 'running' ? 'Analisando evidências…' : 'Análise profunda com AI';
  if (!job) status.textContent = data.ready ? 'Pré-requisitos completos. A execução usa somente o modelo local configurado.' : 'Complete os gates bloqueados antes de iniciar.';
  else if (job.state === 'running') status.textContent = 'Correlacionando DAST e REA com o modelo local. Nenhum candidato será promovido automaticamente.';
  else if (job.state === 'failed' || job.state === 'interrupted') status.textContent = job.reason || 'Análise profunda interrompida.';
  else if (job.state === 'complete') status.textContent = `Concluída · ${job.review.correlations.length} correlação(ões) · revisão humana obrigatória.`;
  const preparation=data.preparation,reaReady=(data.gates||[]).some(item=>item.id==='rea-evidence'&&item.passed);
  const prepare=document.querySelector('#prepareDeepRea');
  prepare.disabled=deepDastBusy||preparation?.state==='running'||reaReady||!data.lab?.apk_sha256;
  prepare.textContent=preparation?.state==='running'?'Preparando REA…':reaReady?'REA preparado':'Preparar REA deste APK';
  document.querySelector('#deepReaStatus').textContent=reaReady?'REA disponível para este APK. Reconstrução Java completa pode ser aberta em Reverse.':preparation?.reason||preparation?.detail||'Extração local do APK e inspeção estática; o app não será executado pelo REA.';
  document.querySelector('#deepEngagementForm').hidden=!!data.lab?.engagement;
  engagementBound=!!data.lab?.engagement;syncEngagementStepper();
  const output = document.querySelector('#deepDastResult'); output.replaceChildren(); output.hidden = job?.state !== 'complete';
  if (job?.state !== 'complete') return;
  const summary = document.createElement('p'); summary.className = 'deep-summary'; summary.textContent = job.review.summary; output.append(summary);
  const ledger = document.createElement('div'); ledger.className = 'deep-ledger';
  const facts = [
    ['Finding', 'Não promovido'],
    ['Revisão independente', job.independently_verified ? 'Sim' : 'Pendente'],
    ['JEV DONE', job.jev?.done_allowed ? 'Gates aceitos' : 'Bloqueado'],
    ['Executor JEV', job.jev?.executor_invoked ? 'Executado' : 'Contrato somente'],
  ];
  facts.forEach(([label,value]) => { const cell=document.createElement('div'); const strong=document.createElement('strong'); strong.textContent=value; const span=document.createElement('span'); span.textContent=label; cell.append(strong,span); ledger.append(cell); }); output.append(ledger);
  const correlations = document.createElement('section'); const heading = document.createElement('h4'); heading.textContent = 'Correlações atribuídas'; correlations.append(heading);
  job.review.correlations.forEach(item => { const row=document.createElement('details'); const title=document.createElement('summary'); title.textContent=`${item.title} · ${item.status} · ${item.confidence}`; const analysis=document.createElement('p'); analysis.textContent=item.analysis; const refs=document.createElement('code'); refs.textContent=item.evidence_ids.join(' · '); row.append(title,analysis,refs); correlations.append(row); }); output.append(correlations);
  [['Hipóteses',job.review.hypotheses],['Desconhecidos',job.review.unknowns],['Próximos testes',job.review.next_tests]].forEach(([title,items]) => { const section=document.createElement('section'); const heading=document.createElement('h4'); heading.textContent=title; const list=document.createElement('ul'); items.forEach(text => { const li=document.createElement('li'); li.textContent=text; list.append(li); }); section.append(heading,list); output.append(section); });
}
async function refreshDeepDast() {
  if (deepDastPolling) return; deepDastPolling = true;
  const requested=dastTarget().id;
  try { const response=await fetch('/api/dynamic/deep'+dastQuery(),{cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error('Não foi possível verificar a correlação deste aparelho.');const data=await response.json();if(dastTarget().id===requested)renderDeepDast(data); }
  catch (error) {if(dastTarget().id===requested){document.querySelector('#deepDastStatus').textContent=error.message;document.querySelector('#deepAnalyzeDast').disabled=true;}}
  finally { deepDastPolling=false; }
}
async function deepDastAction(action,extra={}) {
  if(deepDastBusy)return;
  const target=dastTarget(),requested=target.id;
  deepDastBusy=true;
  document.querySelector('#deepAnalyzeDast').disabled=true;document.querySelector('#prepareDeepRea').disabled=true;
  try {await authorizedPost('/api/dynamic/deep',{...dastPayload(),action,package_id:target.package_id,apk_sha256:target.apk_sha256,...extra});}
  catch(error){if(dastTarget().id===requested){notify(error.message);document.querySelector('#deepDastStatus').textContent=error.message;}}
  finally {deepDastBusy=false;await refreshDeepDast();}
}
document.querySelector('#deepAnalyzeDast').addEventListener('click',()=>deepDastAction('start'));
document.querySelector('#prepareDeepRea').addEventListener('click',()=>deepDastAction('prepare-rea'));
document.querySelector('#deepEngagementForm').addEventListener('submit',event=>{event.preventDefault();void deepDastAction('set-engagement',{engagement:document.querySelector('#deepEngagement').value.trim()});});
refreshDeepDast();
// Ticker único do dinâmico (consolida dast/frida e proxy): um só timer que
// despacha pela aba ativa, pausado em background por everyVisible.
everyVisible(() => {
  const dast = document.querySelector('#tab-dast').classList.contains('active');
  const frida = document.querySelector('#tab-frida').classList.contains('active');
  const proxy = document.querySelector('#tab-proxy').classList.contains('active');
  if (dast || frida) { refreshDynamic(); if (dast) refreshDeepDast(); }
  if (proxy) { loadNetwork(); refreshProxyStatus(); }
}, 2000);
document.querySelector('#openGhidra').addEventListener('click', () => notify('Selecione uma biblioteca nativa .so antes de abrir no Ghidra'));

async function refreshProxyStatus() {
  const port = Number(document.querySelector('#proxyPort').value);
  try {
    const payload = await fetchJson(`/api/proxy?port=${port}`, { cache: "no-store" });
    const connected = payload.configured && payload.listener;
    const active = connected && payload.native_listener && (!payload.direct_capture_required || payload.direct_capture);
    document.querySelector('#proxyStatus').textContent = payload.native_listener ? `Porta ${port} usada pelo HuntMob. Use outra porta com listener do Burp.` : payload.listener ? `Listener externo ativo · Android ${payload.configured ? 'roteado aqui' : payload.device_proxy_set ? `roteado a ${payload.device_proxy}` : 'sem rota'}` : `Nenhum listener em 127.0.0.1:${port}`;
    document.querySelector('#configureProxy').disabled = !payload.listener || payload.native_listener;
    document.querySelector('#proxyBadge').textContent = active ? 'Capturando' : connected && payload.native_listener ? 'App sem captura' : connected ? 'Burp externo' : 'Desconectado';
    document.querySelector('#proxyBadge').dataset.state = active ? 'active' : connected ? 'warning' : 'offline';
    document.querySelector('#captureTitle').textContent = active ? 'Captura ativa' : connected ? 'Rota ativa' : 'Captura inativa';
    document.querySelector('.proxy-commandbar').dataset.state = active ? 'active' : connected ? 'warning' : 'offline';
    document.querySelector('#proxyRouteSummary').textContent = connected ? `${payload.native_listener ? 'HuntMob' : 'Burp externo'} · ${payload.device_proxy}` : payload.device_proxy_set ? `Rota em outra porta · ${payload.device_proxy}` : 'Sem rota no Android';
    document.querySelector('#captureHelp').textContent = connected && !payload.native_listener ? 'Listener externo: veja o tráfego no Burp configurado ou escolha uma porta livre para a captura HuntMob.' : connected && !active ? payload.capture_note || 'Rota de proxy ativa, mas o tráfego do app ainda não foi confirmado.' : !active ? 'Captura desligada. Clique em Iniciar captura antes do login no app.' : payload.capture_note || 'Proxy Android ativo. O app precisa usar essa rota; HTTPS exige a CA do laboratório.';
    document.querySelector('#startCapture').hidden = active;
    document.querySelector('#stopCapture').hidden = !payload.device_proxy_set;
  } catch (error) { document.querySelector('#proxyStatus').textContent = error.message; }
}

async function proxyAction(action) {
  const port = Number(document.querySelector('#proxyPort').value);
  const payload = await authorizedPost('/api/proxy', { action, port });
  const active = action !== 'clear';
  document.querySelector('#captureTitle').textContent = active ? 'Captura ativa' : 'Captura inativa';
  document.querySelector('#startCapture').hidden = active;
  document.querySelector('#stopCapture').hidden = !active;
  if (payload.managed) {
    document.querySelector('#captureHelp').textContent = payload.capture_note || 'Captura gerenciada integrada abaixo. Para HTTPS, instale a CA do laboratório no device.';
    loadNetwork();
  }
  await refreshProxyStatus();
  return payload;
}

document.querySelector('#startCapture').addEventListener('click', async () => {
  try { await proxyAction('start-managed'); notify('Proxy gerenciado iniciado e aplicado ao device'); } catch (error) { notify(error.message); }
});
document.querySelector('#configureProxy').addEventListener('click', async () => {
  try { await proxyAction('configure'); notify('Listener Burp aplicado ao device'); } catch (error) { notify(error.message); }
});
document.querySelector('#stopCapture').addEventListener('click', async () => {
  try { await proxyAction('clear'); notify('Rota de proxy removida do device'); } catch (error) { notify(error.message); }
});
document.querySelector('#proxyPort').addEventListener('change', refreshProxyStatus);

function showProxyView(view) {
  document.querySelectorAll('[data-proxy-view]').forEach(button => {
    const active = button.dataset.proxyView === view;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  document.querySelectorAll('.proxy-view').forEach(panel => {
    const active = panel.id === `proxy-view-${view}`;
    panel.hidden = !active;
    panel.classList.toggle('active', active);
  });
  document.querySelector('#tab-proxy').scrollTop = 0;
}
document.querySelectorAll('[data-proxy-view]').forEach(button => button.addEventListener('click', () => showProxyView(button.dataset.proxyView)));
document.querySelector('#backToHistory').addEventListener('click', () => showProxyView('history'));
document.querySelector('#proxyFocusToggle').addEventListener('click', () => {
  setProxyFocus(!workspace.classList.contains('proxy-focus'));
});
document.querySelector('#openProxyCertSettings').addEventListener('click', async () => {
  try { await authorizedPost('/api/proxy', { action: 'open-cert-settings' }); notify('Ajustes de segurança abertos no Android'); }
  catch (error) { notify(error.message); }
});
document.querySelector('#sendProxyCa').addEventListener('click', async event => {
  const button = event.currentTarget;
  const file = document.querySelector('#proxyCaFile').files?.[0];
  const status = document.querySelector('#proxyCaStatus');
  if (!file || !/\.(cer|crt|pem)$/i.test(file.name) || !file.size || file.size > 1024 * 1024) { status.textContent = 'Selecione uma CA pública .cer, .crt ou .pem de até 1 MB.'; return; }
  if (devicePlatform !== 'android' || !activeLab.id) { status.textContent = 'Selecione um Android ligado neste laboratório.'; return; }
  const bytes = new Uint8Array(await file.arrayBuffer());
  const content = new TextDecoder().decode(bytes);
  if (/-----BEGIN [^-]*PRIVATE KEY-----/.test(content) || (/\.pem$/i.test(file.name) && !/-----BEGIN CERTIFICATE-----/.test(content))) { status.textContent = 'Arquivo recusado: envie somente o certificado público.'; return; }
  button.disabled = true; status.textContent = 'Enviando CA para Downloads/HuntMob…';
  try {
    const response = await sessionFetch('/api/device/drop', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-HuntMob-Approved': 'true', 'X-HuntMob-Workspace': activeLab.id, 'X-HuntMob-Device': activeLab.id, 'X-HuntMob-Filename': encodeURIComponent(file.name) }, body: file });
    const result = await response.json();
    if (!response.ok || !result.ok || result.kind !== 'file') throw new Error(result.reason || 'Envio não concluído.');
    status.textContent = `${file.name} enviado a Downloads/HuntMob. Instalação e confiança ainda não verificadas.`;
    notify('CA enviada; instale nos ajustes do Android');
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});

let networkFlows = [];
let networkHost = '';
let networkSelection;
let replayBusy = false;
let detailEpoch = 0;
let networkLoading = false;
let networkRenderSignature = '';
function renderNetworkDetail() {
  if (!networkSelection) return;
  detailEpoch++;
  document.querySelector('#networkSelected').textContent = `${networkSelection.method} ${networkSelection.host}${networkSelection.path}`;
  const request = networkSelection.request;
  document.querySelector('#requestEditor').value = `${networkSelection.method} ${networkSelection.path} HTTP/1.1\n${Object.entries(request.headers || {}).map(([key, value]) => `${key}: ${value}`).join('\n')}\n\n${request.body || ''}`;
  renderResponse(networkSelection.response, networkSelection.status);
  document.querySelector('#sendRequest').disabled = false;
  document.querySelector('#sendStatus').textContent = networkSelection.status != null ? 'Resposta capturada' : networkSelection.state === 'pending' ? 'Aguardando resposta' : 'Falha de conexão · sem resposta HTTP';
}
function renderResponse(message, status) {
  if (status == null) {
    document.querySelector('#responseEditor').textContent = networkSelection?.state === 'pending' ? 'Requisição capturada. Aguardando resposta do backend.' : `Requisição capturada, mas o backend ${networkSelection?.host}:${networkSelection?.port} não devolveu resposta HTTP. Verifique se o serviço está disponível.`;
    return;
  }
  document.querySelector('#responseEditor').textContent = `HTTP ${status}\n${Object.entries(message.headers || {}).map(([key, value]) => `${key}: ${value}`).join('\n')}\n\n${message.body || ''}`;
}
function renderNetwork() {
  const signature = JSON.stringify([networkFlows, networkHost, networkSelection?.id, ...['#networkSearch', '#networkMethod', '#networkStatus'].map(selector => document.querySelector(selector).value)]);
  if (signature === networkRenderSignature) return;
  networkRenderSignature = signature;
  const hosts = [...new Set(networkFlows.map(flow => flow.host))].sort();
  document.querySelector('#networkStats').textContent = `${networkFlows.length} requisições · ${hosts.length} hosts · ${networkFlows.filter(flow => flow.status >= 400).length} erros HTTP · ${networkFlows.filter(flow => flow.state === 'error' || (flow.status == null && flow.state !== 'pending')).length} falhas de conexão`;
  const hostList = document.querySelector('#networkHosts');
  hostList.replaceChildren();
  ['', ...hosts].forEach(host => {
    const button = document.createElement('button');
    button.textContent = host || 'Todos os hosts';
    button.className = host === networkHost ? 'selected' : '';
    button.addEventListener('click', () => { networkHost = host; renderNetwork(); });
    hostList.append(button);
  });
  const query = document.querySelector('#networkSearch').value.toLowerCase();
  const method = document.querySelector('#networkMethod').value;
  const status = document.querySelector('#networkStatus').value;
  const flows = networkFlows.filter(flow => (!networkHost || flow.host === networkHost) && (!method || flow.method === method) && (!status || String(flow.status).startsWith(status)) && `${flow.host}${flow.path}`.toLowerCase().includes(query));
  const rows = document.querySelector('#networkRows');
  rows.replaceChildren();
  if (!flows.length) {
    const empty = document.createElement('p');
    empty.textContent = 'Nenhuma requisição neste filtro. Se o login não aparecer, verifique se o app usa o proxy e se o backend de teste está configurado.';
    rows.append(empty);
  }
  flows.slice().reverse().forEach(flow => {
    const row = document.createElement('button');
    row.className = 'network-row';
    const methodCell = document.createElement('span'); methodCell.className = 'network-method'; methodCell.textContent = flow.method;
    const urlCell = document.createElement('span'); urlCell.className = 'network-url'; urlCell.textContent = `${flow.host}${flow.path}`;
    const statusCell = document.createElement('span'); statusCell.className = 'network-status'; statusCell.textContent = flow.status ?? (flow.state === 'pending' ? '…' : 'erro');
    const timeCell = document.createElement('span'); timeCell.className = 'network-time'; timeCell.textContent = flow.duration_ms == null ? '—' : `${flow.duration_ms} ms`;
    row.append(methodCell, urlCell, statusCell, timeCell);
    row.classList.toggle('selected', networkSelection?.id === flow.id);
    row.addEventListener('click', () => { if (replayBusy) return; networkSelection = flow; renderNetworkDetail(); renderNetwork(); showProxyView('replay'); });
    rows.append(row);
  });
}
async function loadNetwork() {
  if (networkLoading) return;
  networkLoading = true;
  const epoch = detailEpoch;
  try {
    const response = await fetch('/api/network', {cache: 'no-store'});
    if (!response.ok) throw new Error('Captura indisponível');
    const payload = await response.json();
    if (epoch !== detailEpoch) return;
    networkFlows = payload.flows || [];
    const completed = networkSelection?.state === 'pending' && networkFlows.find(flow => flow.id === networkSelection.id && flow.state !== 'pending');
    if (completed && !replayBusy && document.querySelector('#sendStatus').textContent === 'Aguardando resposta') {
      networkSelection = completed;
      renderResponse(completed.response || {}, completed.status);
      document.querySelector('#sendStatus').textContent = completed.status != null ? 'Resposta capturada' : 'Falha de conexão · sem resposta HTTP';
    }
    renderNetwork();
    // Keep the edited request and the result of an explicit Send unchanged.
  } catch (error) { networkRenderSignature = ''; document.querySelector('#networkStats').textContent = error.message; }
  finally { networkLoading = false; }
}
document.querySelector('#openProxyWeb').addEventListener('click', loadNetwork);
document.querySelector('#clearNetwork').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await authorizedPost('/api/network/clear', {});
    detailEpoch++; networkFlows = []; networkSelection = undefined; networkHost = '';
    document.querySelector('#networkSearch').value = '';
    document.querySelector('#networkMethod').value = '';
    document.querySelector('#networkStatus').value = '';
    document.querySelector('#networkSelected').textContent = 'Selecione uma requisição';
    document.querySelector('#requestEditor').value = '';
    document.querySelector('#responseEditor').textContent = 'A captura foi limpa. Novas requisições aparecerão aqui.';
    document.querySelector('#sendRequest').disabled = true;
    document.querySelector('#sendStatus').textContent = 'Aguardando seleção';
    renderNetwork(); notify('Captura limpa neste laboratório');
  } catch (error) { notify(error.message); }
  finally { button.disabled = false; }
});
['#networkSearch', '#networkMethod', '#networkStatus'].forEach(selector => document.querySelector(selector).addEventListener('input', renderNetwork));
document.querySelector('#sendRequest').addEventListener('click', async () => {
  if (!networkSelection || replayBusy) return;
  const selectedId = networkSelection.id;
  const epoch = detailEpoch;
  const button = document.querySelector('#sendRequest');
  const status = document.querySelector('#sendStatus');
  const raw = document.querySelector('#requestEditor').value.replace(/\r\n/g, '\n');
  const boundary = raw.indexOf('\n\n');
  const head = (boundary < 0 ? raw : raw.slice(0, boundary)).split('\n');
  const first = head.shift().match(/^([A-Z]+) (\S+) HTTP\/1\.[01]$/);
  if (!first) { status.textContent = 'Use MÉTODO /caminho HTTP/1.1 na primeira linha.'; return; }
  const headers = {};
  for (const line of head) {
    const colon = line.indexOf(':');
    if (colon <= 0) { status.textContent = 'Header inválido: use Nome: valor.'; return; }
    headers[line.slice(0, colon).trim()] = line.slice(colon + 1).trim();
  }
  replayBusy = true;
  button.disabled = true;
  status.textContent = 'Enviando…';
  document.querySelector('#responseEditor').textContent = 'Aguardando resposta deste envio…';
  try {
    const result = await authorizedPost('/api/network/send', {flow_id: selectedId, method: first[1], path: first[2], headers, body: boundary < 0 ? '' : raw.slice(boundary + 2)});
    if (epoch !== detailEpoch) return;
    renderResponse(result, result.status);
    status.textContent = `${result.status} · ${result.duration_ms} ms${result.truncated ? ' · preview limitado' : ''}`;
  } catch (error) {
    if (epoch === detailEpoch) {
      status.textContent = 'Envio não concluído';
      document.querySelector('#responseEditor').textContent = error.message;
    }
  }
  finally { replayBusy = false; button.disabled = !networkSelection; }
});
// (proxy consolidado no ticker único do dinâmico acima)
loadNetwork();
const createLabButton = document.querySelector('#createLab');
const labError = document.querySelector('#labError');

function resetNewLabProgress() {
  createLabButton.disabled = false;
  createLabButton.textContent = 'Criar e iniciar laboratório';
  labError.hidden = true;
  labError.textContent = '';
}

document.querySelector('#newLab').addEventListener('click', () => {
  resetNewLabProgress();
  if (runtimeDevice?.state === 'on') {
    labError.textContent = document.querySelector('#labPlatform').value==='ios'?'O iOS atual será preservado. Será criado um dispositivo separado.':'O lab atual será preservado. Este APK terá um Android separado e limpo.';
    labError.hidden = false;
    createLabButton.disabled = false;
  }
  updateLabPlatform();
  newLabDialog.showModal();
});
document.querySelector('#closeNewLab').addEventListener('click', () => newLabDialog.close('cancel'));
newLabDialog.addEventListener('close', resetNewLabProgress);
function playPackage(value) {
  const text=value.trim();
  if(!text || validPackage(text))return text;
  let url;
  try {url=new URL(text);}catch {throw new Error('Use um Package ID ou link oficial https://play.google.com/store/apps/details?id=…');}
  const packageId=url.searchParams.get('id');
  if(url.protocol!=='https:' || url.hostname!=='play.google.com' || url.port || url.username || url.password || url.pathname!=='/store/apps/details' || url.searchParams.getAll('id').length!==1 || !packageId || !validPackage(packageId))throw new Error('Link inválido. Use a página oficial do app no Google Play.');
  return packageId;
}
function updateLabSource() {
  const source = document.querySelector('#labSource').value;
  const labels = {
    empty: 'Cria um lab vazio separado. O lab atual será preservado.',
    upload: 'Selecione um APK/AAB local; o worker calculará SHA-256 antes da instalação.',
    firebase: 'O worker usará uma referência Firebase e credenciais guardadas no servidor.',
    'signed-url': 'A URL assinada será resolvida apenas no worker e nunca ficará no navegador.',
    'play-manual': 'A instalação pela loja requer login e autorização manual dentro do device.',
  };
  document.querySelector('#artifactField').hidden = source !== 'upload';
  const ios=document.querySelector('#labPlatform').value==='ios';
  const play=!ios&&source==='play-manual';
  document.querySelector('#labPackageLabel').textContent=ios?'Bundle ID':play?'Link do Google Play ou Package ID':'Package ID';
  document.querySelector('#labPackageHelp').textContent=ios?'opcional; detectado do build .app':play?'opcional; deixe vazio para abrir a loja':'opcional; detectado do APK';
  document.querySelector('#labPackage').placeholder=play?'https://play.google.com/store/apps/details?id=…':'br.com.empresa.app';
  if(!ios)document.querySelector('#labVersionHelp').textContent=play?'A imagem oficial Google Play para este worker será preparada no primeiro uso. Licenças pendentes precisam ser aceitas no SDK Manager.':'A imagem AOSP para este worker será preparada no primeiro uso. Licenças pendentes precisam ser aceitas no SDK Manager.';
  document.querySelector('#labLegacySdk').closest('label').hidden=ios||play;
  document.querySelector('#labPlan').textContent=ios?(source==='upload'?'Instala um build .app para Simulator, compactado em ZIP. Não instala IPA físico nem App Store.':'Cria um iOS Simulator separado e preserva o atual.'):labels[source];
  if(play){document.querySelector('#labRootMode').value='stock';document.querySelector('#labPlan').textContent='Prepara a imagem oficial e abre a Play Store em um Android separado. Entre na loja e instale o app pela tela do dispositivo. O laboratório atual será preservado. Disponibilidade e compatibilidade dependem do app.';}
  document.querySelector('#labRootMode').disabled=!ios&&source==='play-manual';
}
document.querySelector('#labSource').addEventListener('change', updateLabSource);
document.querySelector('#newLabForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  let packageValue = document.querySelector('#labPackage').value.trim();
  const source = document.querySelector('#labSource').value;
  const errorBox = labError;
  errorBox.hidden = true;
  if(document.querySelector('#labPlatform').value==='android' && source==='play-manual') {
    try {packageValue=playPackage(packageValue);}catch(error){errorBox.textContent=error.message;errorBox.hidden=false;return;}
  }
  if (document.querySelector('#labPlatform').value==='android' && packageValue && !validPackage(packageValue)) {
    errorBox.textContent = 'Package ID inválido. Use o formato br.com.empresa.app ou deixe vazio para detecção automática.';
    errorBox.hidden = false;
    return;
  }
  if (!document.querySelector('#labApproval').checked) {
    errorBox.textContent = 'Confirme a autorização para usar este laboratório antes de iniciar.';
    errorBox.hidden = false;
    return;
  }
  if (source === 'upload' && !document.querySelector('#labArtifact').files.length) {
    errorBox.textContent = document.querySelector('#labPlatform').value==='ios'?'Selecione um build .app.zip ou escolha iOS vazio.':'Selecione um APK ou escolha Android vazio.';
    errorBox.hidden = false;
    return;
  }
  try {
    createLabButton.disabled = true;
    if (document.querySelector('#labPlatform').value === 'ios') {
      if (!['empty','upload'].includes(source)) throw new Error('Selecione lab vazio ou build local para este runtime.');
      if (source==='upload' && !document.querySelector('#labArtifact').files[0].name.toLowerCase().endsWith('.zip')) throw new Error('Este runtime requer .app.zip para Simulator.');
      createLabButton.textContent='Iniciando iOS…';
      errorBox.textContent='Preparando modelo e versão selecionados. O primeiro boot pode levar alguns minutos.';errorBox.hidden=false;
      await authorizedPost('/api/ios/action', {action:'new-lab', runtime:document.querySelector('#labVersion').value, model:document.querySelector('#labModel').value, access:document.querySelector('#labIosAccess').value});
      if (source === 'upload') {
        const artifact=document.querySelector('#labArtifact').files[0];
        if (!artifact.name.toLowerCase().endsWith('.zip')) throw new Error('Este runtime requer .app.zip para Simulator. IPA usa o runtime próprio ainda indisponível.');
        const response=await sessionFetch('/api/ios/upload',{method:'POST',headers:{'Content-Type':'application/zip','X-HuntMob-CSRF':csrfToken,'X-HuntMob-Approved':'true'},body:artifact});
        const result=await response.json();if(!result.ok)throw new Error(result.reason || 'Instalação iOS recusada.');
      }
      newLabDialog.close();await switchDevicePlatform('ios');notify('Laboratório iOS iniciado.');return;
    }
    createLabButton.textContent = 'Iniciando…';
    errorBox.textContent = 'Preparando a imagem escolhida e iniciando o Android… A primeira instalação pode levar alguns minutos.';
    errorBox.hidden = false;
    if (source === 'upload') {
      const artifact = document.querySelector('#labArtifact').files[0];
      if (!artifact.name.toLowerCase().endsWith('.apk')) throw new Error('Envie um APK instalável. AAB precisa ser convertido antes.');
      errorBox.textContent = 'Enviando APK, preparando Android e abrindo o app…';
      if (!csrfToken) csrfToken = await fetchSessionToken();
      const response = await sessionFetch('/api/device/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/vnd.android.package-archive', 'X-HuntMob-CSRF': csrfToken, 'X-HuntMob-Approved': 'true', 'X-HuntMob-New-Lab': 'true', 'X-HuntMob-Legacy-SDK': String(document.querySelector('#labLegacySdk').checked), 'X-HuntMob-Root-Mode': document.querySelector('#labRootMode').value, 'X-HuntMob-Android-API':document.querySelector('#labVersion').value },
        body: artifact,
      });
      const result = await response.json();
      if (!response.ok || !result.launched) throw new Error(result.reason || 'Não foi possível abrir o APK');
      await selectApp(result.package_id);
      await loadInstalledApps();
    } else if (source === 'play-manual') {
      errorBox.textContent='Preparando Google Play e iniciando o Android… A primeira preparação pode levar alguns minutos.';
      await deviceAction('new-play-lab',{package_id:packageValue,android_api:Number(document.querySelector('#labVersion').value)});
    } else if (source === 'empty') {
      await deviceAction('new-lab', {root_mode: document.querySelector('#labRootMode').value,android_api:Number(document.querySelector('#labVersion').value)});
    } else {
      throw new Error('Esta origem ainda não está integrada. Use APK local ou Device vazio.');
    }
    newLabDialog.close();
    if(devicePlatform!=='android')await switchDevicePlatform('android');
    await loadRuntime();
    notify(source==='play-manual'?'Play Store aberta. Entre na loja para instalar o app.':'Laboratório Android pronto');
  } catch (error) {
    if(error.payload?.lab_created) {
      newLabDialog.close();
      if(devicePlatform!=='android')await switchDevicePlatform('android');
      await loadRuntime();
      notify('Laboratório criado. '+error.message);
      return;
    }
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    createLabButton.disabled = false;
    createLabButton.textContent = 'Criar e iniciar laboratório';
  }
});
const sessionDialog = document.querySelector('#sessionDialog');
let dialogLabId = '';
function openLabShutdown() {
  if (devicePlatform !== 'android' || !activeLab.id || labLifecycleBusy) return;
  dialogLabId = activeLab.id;
  document.querySelector('#sessionError').hidden = true;
  document.querySelector('#sessionDialogNote').textContent = labIsSaved()
    ? 'Este lab já está salvo. Desligar mantém apps e dados para retomada. Descartar apaga apenas o AVD e os dados deste lab.'
    : 'Salvar e desligar guarda apps e dados para retomada. Desligar sem salvar apaga o AVD e os dados deste lab.';
  document.querySelector('#powerOffDevice').textContent = labIsSaved() ? 'Desligar e preservar' : 'Salvar e desligar';
  document.querySelector('#destroyDevice').textContent = labIsSaved() ? 'Descartar este lab' : 'Desligar sem salvar';
  sessionDialog.showModal();
}
document.querySelector('#stopDevice').addEventListener('click', openLabShutdown);
document.querySelector('#closeLabButton').addEventListener('click', openLabShutdown);
document.querySelector('#saveLabButton').addEventListener('click', async () => {
  if (labLifecycleBusy || devicePlatform !== 'android' || !activeLab.id || labIsSaved()) return;
  const labId = activeLab.id;
  labLifecycleBusy = true; syncLabLifecycleButtons();
  try {
    await deviceAction('save-lab', {lab_id: labId});
    await loadRuntime(); await loadSavedLabs();
    notify('Laboratório salvo; aparelho continua ligado');
  } catch (error) { notify(error.message); }
  finally { labLifecycleBusy = false; syncLabLifecycleButtons(); }
});
document.querySelector('#rebootDevice').addEventListener('click', async () => {
  notify('Reiniciando Android…');
  try { await deviceAction('reboot'); await loadRuntime(); notify('Android reiniciado'); } catch (error) { notify(error.message); }
});
async function finishLabShutdown(action) {
  if (labLifecycleBusy || !dialogLabId || dialogLabId !== activeLab.id) return;
  labLifecycleBusy = true; syncLabLifecycleButtons();
  document.querySelector('#powerOffDevice').disabled = true;
  document.querySelector('#destroyDevice').disabled = true;
  try {
    await deviceAction(action, {lab_id: dialogLabId});
    sessionDialog.close(); dialogLabId = '';
    stopDeviceScreen();
    await loadRuntime(); await loadSavedLabs(); await loadWorkspaceDevices();
    notify(action === 'save-stop' ? 'Lab salvo; aparelho desligado' : 'Lab atual e seus dados descartados');
  } catch (error) {
    const box = document.querySelector('#sessionError');
    box.textContent = error.message; box.hidden = false;
  } finally {
    labLifecycleBusy = false;
    document.querySelector('#powerOffDevice').disabled = false;
    document.querySelector('#destroyDevice').disabled = false;
    syncLabLifecycleButtons();
  }
}
document.querySelector('#powerOffDevice').addEventListener('click', () => finishLabShutdown('save-stop'));
document.querySelector('#destroyDevice').addEventListener('click', () => finishLabShutdown('discard-lab'));
loadRuntime();
refreshProxyStatus();
everyVisible(loadRuntime, 2500);

const interactiveScreens = [document.querySelector('#deviceScreen'),document.querySelector('#deviceVideo')];
const keyboardScope=()=>devicePlatform+':'+(devicePlatform==='ios'?iosInfo?.lab?.udid:activeLab.id)+':'+screenGeneration;
const screenKeyboard=window.huntmobInteraction.inputQueue(input=>authorizedPost(input.route,input.payload),scope=>scope===keyboardScope(),error=>notify(error.message));
let pointerStart;
function screenPoint(event) {
  const interactiveScreen = event.currentTarget;
  const rect = interactiveScreen.getBoundingClientRect();
  const frameWidth = Number(interactiveScreen.dataset.frameWidth || interactiveScreen.naturalWidth);
  const frameHeight = Number(interactiveScreen.dataset.frameHeight || interactiveScreen.naturalHeight);
  const scale = Math.min(rect.width / frameWidth, rect.height / frameHeight);
  const width = frameWidth * scale;
  const height = frameHeight * scale;
  return { x: (event.clientX - rect.left - (rect.width - width) / 2) / width, y: (event.clientY - rect.top - (rect.height - height) / 2) / height };
}
let touchQueue = [], touchSending = false, touchLive = false, touchTarget, activePointer;
async function sendLiveTouch(event) {
  const last=touchQueue[touchQueue.length-1];
  if (event.phase==='move' && last?.phase==='move' && last.target===event.target) touchQueue[touchQueue.length-1]=event;
  else touchQueue.push(event);
  if (touchSending) return; touchSending = true;
  try { while (touchQueue.length) { const {target,...next} = touchQueue.shift(); await authorizedPost(target.route,{action:'touch',...next,...target.identity}); } }
  catch(error) { touchQueue=[]; notify(error.message); }
  finally { touchSending=false; }
}
function cancelLiveTouch() {
  if (touchLive && pointerStart) sendLiveTouch({phase:'cancel',...pointerStart,target:touchTarget});
  pointerStart=undefined;touchLive=false;activePointer=undefined;
}
window.addEventListener('blur',cancelLiveTouch);
document.addEventListener('visibilitychange',()=>{if(document.hidden)cancelLiveTouch();});
interactiveScreens.forEach(interactiveScreen => {
interactiveScreen.style.touchAction = 'none';
interactiveScreen.tabIndex = 0;
interactiveScreen.addEventListener('pointerdown', event => {
  if(event.button!==0)return;
  event.preventDefault();
  if (pointerStart) return;
  interactiveScreen.focus({preventScroll:true});
  pointerStart = screenPoint(event);
  if (![pointerStart.x,pointerStart.y].every(value=>Number.isFinite(value)&&value>=0&&value<=1)) {pointerStart=undefined;return;}
  activePointer=event.pointerId;
  interactiveScreen.setPointerCapture(event.pointerId);
  touchLive = devicePlatform==='ios' || directVideoActive;
  touchTarget = devicePlatform==='ios'?{route:'/api/ios/action',identity:{udid:iosInfo?.lab?.udid}}:{route:'/api/device/direct-input',identity:{}};
  if (touchLive) sendLiveTouch({phase:'down',...pointerStart,target:touchTarget});
});
interactiveScreen.addEventListener('dragstart', event => event.preventDefault());
interactiveScreen.addEventListener('pointermove', event => { if (!pointerStart || !touchLive || event.pointerId!==activePointer) return; const point = screenPoint(event); if ([point.x,point.y].every(v=>v>=0&&v<=1)) sendLiveTouch({phase:'move',...point,target:touchTarget}); });
interactiveScreen.addEventListener('pointercancel', cancelLiveTouch);
interactiveScreen.addEventListener('lostpointercapture', cancelLiveTouch);
interactiveScreen.addEventListener('pointerup', async event => {
  if (!pointerStart || event.pointerId!==activePointer) return;
  const end = screenPoint(event);
  const start = pointerStart;
  pointerStart = undefined;
  activePointer=undefined;
  if (![start.x, start.y, end.x, end.y].every(value => value >= 0 && value <= 1)) { if(touchLive) { touchLive=false; await sendLiveTouch({phase:'cancel',...start,target:touchTarget}); } return; }
  if (touchLive) { touchLive=false; await sendLiveTouch({phase:'up',...end,target:touchTarget}); return; }
  const swipe = Math.hypot(end.x - start.x, end.y - start.y) > 0.025;
  try {
    await authorizedPost(devicePlatform === 'ios' ? '/api/ios/action' : '/api/device/input', {action: swipe ? 'swipe' : 'tap', ...start, end_x: end.x, end_y: end.y});
  } catch (error) { notify(error.message); }
});
interactiveScreen.addEventListener('keydown', event => {
  const payload=window.huntmobInteraction.keyboardAction(event,{platform:devicePlatform,mode:devicePlatform==='ios'?'ascii':directVideoActive?'unicode':'adb'});
  if (!payload) return;
  event.preventDefault();
  void screenKeyboard.push({route:devicePlatform==='ios'?'/api/ios/action':directVideoActive?'/api/device/direct-input':'/api/device/input',payload},keyboardScope());
});
});
document.querySelector('#deviceBack').addEventListener('click', async () => {
  try { await authorizedPost(directVideoActive ? '/api/device/direct-input' : '/api/device/input', {action: 'back'}); } catch (error) { notify(error.message); }
});


async function loadEvidence() {
  try {
    const response = await fetch('/api/evidence', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Evidências indisponíveis');
    const payload = await response.json();
    payload.records = payload.records.filter(record => devicePlatform === 'ios' ? record.lab_id === 'ios_' + iosInfo?.lab?.udid : !activeLab.id || record.lab_id === activeLab.id || (activeLab.legacy && !record.lab_id));
    document.querySelector('#evidenceCount').textContent = String(payload.records.length);
    syncEngagementStepper();
    document.querySelector('#evidenceStatus').textContent = payload.invalid_count ? `${payload.invalid_count} registro(s) com falha de integridade. Exportação bloqueada para esses registros.` : payload.records.length ? 'Capturas locais verificadas por SHA-256. Revise dados sensíveis antes de compartilhar.' : 'Capture a tela do device para registrar sua primeira evidência.';
    const list = document.querySelector('#evidenceTimeline');
    list.replaceChildren();
    payload.records.forEach(record => {
      const row = document.createElement('li');
      const time = document.createElement('time');
      time.dateTime = record.created_at;
      time.textContent = new Date(record.created_at).toLocaleString('pt-BR');
      const detail = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = 'Captura de tela · ' + (record.selected_package || record.serial);
      const hash = document.createElement('small');
      hash.textContent = `SHA-256 ${record.sha256}`;
      const link = document.createElement('a');
      link.textContent = 'Exportar captura e metadados';
      link.href = '/api/evidence/export/' + encodeURIComponent(record.id);
      link.className = 'evidence-export';
      detail.append(title, hash, link);
      row.append(time, detail);
      list.append(row);
    });
  } catch (error) {
    document.querySelector('#evidenceStatus').textContent = error.message;
    document.querySelector('#evidenceCount').textContent = '—';
    syncEngagementStepper();
  }
}
document.querySelector('#refreshEvidence').addEventListener('click', loadEvidence);
document.querySelector('#captureEvidence').addEventListener('click', async () => {
  if (devicePlatform === 'ios') { await iosAction('capture'); return; }
  const button = document.querySelector('#captureEvidence');
  button.disabled = true;
  try {
    await authorizedPost('/api/evidence/capture', { package_id: currentSelectedPackage });
    await loadEvidence();
    notify('Captura salva com horário e SHA-256');
  } catch (error) { notify(error.message); }
  finally { button.disabled = runtimeDevice?.state !== 'on'; }
});
async function downloadEvidenceJpeg(record) {
  if (!/^ev_[a-f0-9]{32}$/.test(record?.id)) throw new Error('Identificador da captura inválido.');
  const response = await fetch('/api/evidence/image/' + record.id, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error('Não foi possível ler a captura salva.');
  const png = await response.blob();
  if (png.type !== 'image/png') throw new Error('Formato de captura inesperado.');
  const sourceUrl = URL.createObjectURL(png);
  let image;
  try {
    image = new Image();
    image.src = sourceUrl;
    await image.decode();
    if (!image.naturalWidth || !image.naturalHeight) throw new Error('Captura vazia.');
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    canvas.getContext('2d').drawImage(image, 0, 0);
    const jpeg = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (!jpeg || jpeg.type !== 'image/jpeg') throw new Error('Não foi possível gerar JPEG.');
    const downloadUrl = URL.createObjectURL(jpeg);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = `huntmob-screenshot-${record.id}.jpg`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 30000);
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
}
loadEvidence();


async function loadSavedLabs() {
  const list = document.querySelector('#savedLabs');
  try {
    const response = await fetch('/api/labs', { cache: 'no-store' });
    if (!response.ok) throw new Error('Labs salvos indisponíveis');
    const payload = await response.json();
    if(window.huntmobSidebar){window.huntmobSidebar.labs(payload);return;}
    list.replaceChildren();
    payload.labs.forEach(lab => {
      const button = document.createElement('button');
      button.className = 'saved-lab';
      button.textContent = (lab.package_id || (lab.legacy ? 'Lab anterior' : 'Lab vazio')) + ' · API ' + (lab.android_api || 35) + ' · ' + (lab.root_mode === 'stock' ? 'Google Play' : 'AOSP') + (lab.id === payload.current.id ? ' · atual' : '');
      button.title = 'Retomar ' + lab.id;
      button.addEventListener('click', async () => {
        if (!window.confirm('Retomar este lab? O atual será desligado e preservado.')) return;
        button.disabled = true;
        try {
          await authorizedPost('/api/device/action', { action: 'resume', lab_id: lab.id });
          await loadRuntime();
          await loadSavedLabs();
          notify('Lab retomado com dados preservados');
        } catch (error) { notify(error.message); }
        finally { button.disabled = false; }
      });
      list.append(button);
    });
    if (!payload.labs.length) list.textContent = 'Nenhum lab por aplicativo criado.';
  } catch (error) { list.textContent = error.message; }
}
loadSavedLabs();

async function resumeSavedLab(lab,button){
  if(lab.id===activeLab.id){
    if(devicePlatform!=='android')await switchDevicePlatform('android');
    return;
  }
  if(!window.confirm('Retomar este lab? O atual será desligado e preservado.'))return;
  button.disabled=true;
  try{
    await authorizedPost('/api/device/action',{action:'resume',lab_id:lab.id});
    await loadRuntime();await loadSavedLabs();notify('Lab retomado com dados preservados');
  }catch(error){notify(error.message);}
  finally{button.disabled=false;}
}


async function loadAnalysisStatus() {
  const label = document.querySelector('#analysisEngineState');
  try {
    const response = await fetch('/api/analysis/status', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Não foi possível verificar o motor integrado');
    const payload = await response.json();
    analysisReady = payload.ready === true;
    label.textContent = analysisReady ? 'Motor integrado · pronto' : 'Motor integrado indisponível';
    label.title = analysisReady ? 'Motor e runtime incluídos no HuntMob' : payload.reason;
  } catch (error) {
    analysisReady = false;
    label.textContent = 'Motor integrado indisponível';
    label.title = error.message;
  }
  const button = document.querySelector('#prepareReverse');
  if (button) button.disabled = !analysisReady || !currentSelectedPackage;
  quickReaStart.disabled = quickReaBusy || !quickReaAllowed() || !quickReaPackage.value || !analysisReady;
}
loadAnalysisStatus();


async function restoreReverseWorkspace(packageName, required = false) {
  try {
    const response = await fetch('/api/reverse/workspace?' + new URLSearchParams({ package: packageName }), { cache: 'no-store' });
    if (!response.ok) throw new Error('Decompilação preparada não pôde ser carregada.');
    const payload = await response.json();
    if (currentSelectedPackage !== packageName) throw new Error('O app selecionado mudou.');
    renderReverseWorkspace(payload);
    return payload;
  } catch (error) {
    if (required) throw error;
    /* No previous run: leave the preparation control available. */
  }
}

function renderReverseWorkspace(payload) {
  reverseAnalysis = payload;
  syncEngagementStepper();
  window.dispatchEvent(new CustomEvent('huntmob:reverse', {detail:payload}));
  document.querySelector('#reverseHash').textContent = `SHA256 · ${payload.sha256.slice(0, 8)}…${payload.sha256.slice(-4)}`;
  document.querySelector('#fileName').textContent = 'Selecione um arquivo na árvore';
  const output = document.querySelector('#reverseOutput');
  output.classList.add('workspace-reader');
  output.replaceChildren();
  const status = document.createElement('p');
  status.className = 'analysis-summary';
  status.setAttribute('role', 'status');
  status.textContent = payload.status === 'partial' ? `Java parcial · ${payload.errors_count ?? 'alguns'} erro(s) reportado(s). ${payload.problem_files?.length ? payload.problem_files.length + ' arquivo(s) com trechos para revisão. ' : ''}${payload.fallback_status === 'available' ? 'Instruções de baixo nível geradas sem erros; elas não equivalem a Java totalmente reconstruído.' : payload.fallback_status === 'skipped_large_analysis' ? 'O segundo processamento foi omitido pelo tamanho do aplicativo; revise os arquivos gerados e os trechos com erro.' : payload.warning}` : 'Decompilação concluída. Revise o código antes de registrar findings.';
  const actions = document.createElement('div');
  actions.className = 'reader-actions';
  const retry = document.createElement('button');
  retry.id = 'prepareReverse'; retry.className = 'outline'; retry.textContent = 'Analisar novamente';
  const download = document.createElement('a');
  download.className = 'outline'; download.textContent = 'Baixar arquivos';
  download.href = '/api/reverse/export?' + new URLSearchParams({ package: payload.package_id, run: payload.run_id });
  actions.append(retry, download);
  const info = document.createElement('p');
  info.id = 'reverseFileInfo'; info.className = 'reader-file-info'; info.setAttribute('role', 'status');
  info.textContent = `${payload.files.length} arquivos disponíveis · abra uma pasta à esquerda`;
  const code = document.createElement('pre');
  code.id = 'reverseCode'; code.tabIndex = 0; code.setAttribute('aria-label', 'Conteúdo do arquivo selecionado');
  code.textContent = 'Selecione um arquivo de código, Manifest ou recurso para visualizar aqui.';
  output.append(status, actions, info, code);
  renderReverseTree(payload);
}

function renderReverseTree(payload, query = '') {
  const tree = document.querySelector('#installedApps');
  tree.replaceChildren();
  const search = document.createElement('input');
  search.type = 'search'; search.placeholder = 'Buscar arquivo…'; search.setAttribute('aria-label', 'Buscar arquivo decompilado');
  search.value = query;
  const listing = document.createElement('div');
  tree.append(search, listing);
  const draw = () => {
    listing.replaceChildren();
    const root = document.createElement('details'); root.open = true;
    const summary = document.createElement('summary'); summary.textContent = payload.package_id;
    root.append(summary); listing.append(root);
    const prefix = 'sources/' + payload.package_id.replaceAll('.', '/') + '/';
    const matching = payload.files.filter(path => path.toLowerCase().includes(search.value.toLowerCase()));
    const buckets = [
      ['Precisam de revisão', matching.filter(path => payload.problem_files?.includes(path)).map(path => [path,path]), false],
      ['Código do aplicativo', matching.filter(path => path.startsWith(prefix)).map(path => [path.slice(prefix.length),path]), true],
      ['Bibliotecas', matching.filter(path => path.startsWith('sources/') && !path.startsWith(prefix)).map(path => [path.slice(8),path]), false],
      ['Recursos e Manifest', matching.filter(path => path.startsWith('resources/')).map(path => [path.slice(10),path]), false],
      ['Instruções de baixo nível', matching.filter(path => path.startsWith('instructions/')).map(path => [path.slice(13),path]), false],
      ['Outros arquivos', matching.filter(path => !/^(sources|resources|instructions)\//.test(path)).map(path => [path,path]), false],
    ];
    function addFolder(parent, label, entries, opened = false) {
      const folder = document.createElement('details'); folder.open = opened;
      const heading = document.createElement('summary'); heading.textContent = label + ` (${entries.length})`; folder.append(heading); parent.append(folder);
      let populated = false;
      const populate = () => {
        if (populated || !folder.open) return;
        populated = true;
        const groups = new Map();
        for (const [relative, full] of entries) {
          const slash = relative.indexOf('/');
          if (slash >= 0) {
            const name = relative.slice(0, slash);
            if (!groups.has(name)) groups.set(name, []);
            groups.get(name).push([relative.slice(slash + 1), full]);
          } else {
            const button = document.createElement('button'); button.textContent = relative; button.title = full; button.dataset.sourceFile = full;
            button.addEventListener('click', () => openReverseFile(full)); folder.append(button);
          }
        }
        [...groups.entries()].sort(([a],[b]) => a.localeCompare(b)).forEach(([name, children]) => addFolder(folder,name,children, Boolean(search.value)));
      };
      folder.addEventListener('toggle',populate); populate();
    }
    buckets.filter(([,entries]) => entries.length).forEach(([label,entries,opened]) => addFolder(root,label,entries,opened || Boolean(search.value)));
    if (!matching.length) { const empty = document.createElement('p'); empty.textContent = 'Nenhum arquivo encontrado.'; root.append(empty); }
  };
  search.addEventListener('input',draw); draw();
}

async function openReverseFile(path) {
  const payload = reverseAnalysis;
  if (!payload) return;
  const request = ++reverseFileRequest;
  const info = document.querySelector('#reverseFileInfo');
  const code = document.querySelector('#reverseCode');
  document.querySelector('#fileName').textContent = path;
  info.textContent = 'Abrindo arquivo…'; code.textContent = '';
  document.querySelectorAll('[data-source-file]').forEach(button => button.classList.toggle('selected',button.dataset.sourceFile === path));
  try {
    const response = await fetch('/api/reverse/file?' + new URLSearchParams({ package: payload.package_id, run: payload.run_id, path }), { cache:'no-store' });
    if (!response.ok) throw new Error('Arquivo indisponível. Atualize ou execute a análise novamente.');
    const file = await response.json();
    if (request !== reverseFileRequest || reverseAnalysis !== payload) return;
    code.textContent = file.content;
    info.textContent = `${file.size.toLocaleString('pt-BR')} bytes · ${file.format === 'hex' ? 'visualização hexadecimal' : path.startsWith('instructions/') ? 'instruções de baixo nível · somente leitura' : 'somente leitura'}${file.truncated ? ' · prévia limitada; baixe os arquivos para ler tudo' : ''}`;
    code.scrollTop = 0;
  } catch (error) {
    if (request !== reverseFileRequest) return;
    info.textContent = error.message;
  }
}

// Device controls use fixed, bounded worker operations; no command text is accepted.
function clearReportDetails() {
  document.querySelector('#nativeMetrics').hidden = true;
  document.querySelector('#nativeObservations').replaceChildren();
  document.querySelector('#nativeLimitations').replaceChildren(); document.querySelector('#nativeManualChecks').replaceChildren();
}
const controlDialog = document.querySelector('#deviceControlDialog');
document.querySelector('#deviceControlForm').addEventListener('submit', event => event.preventDefault());
document.querySelector('#closeDeviceControl').addEventListener('click', () => controlDialog.close());
document.querySelector('#closeToolbox').addEventListener('click', () => setAnalysisOpen(false,true));
document.querySelectorAll('[data-control-panel]').forEach(button => button.addEventListener('click', () => {
  document.querySelector('#deviceControlForm .eyebrow').textContent=(window.huntmobTools?.isIos()??devicePlatform==='ios')?'LABORATÓRIO IOS':'LABORATÓRIO ANDROID';
  const panel = button.dataset.controlPanel;
  if (panel==='battery') {
    document.querySelector('[data-control-section="battery"] .privacy-note').textContent=(window.huntmobTools?.isIos()??devicePlatform==='ios')?'Altera o indicador da barra de status. Não simula a carga nas APIs do aplicativo.':'Teste o comportamento do app em carga baixa. Restaurar remove a simulação.';
    document.querySelector('[data-control-action="battery"]').textContent=(window.huntmobTools?.isIos()??devicePlatform==='ios')?'Aplicar indicador':'Aplicar carga';
  }
  const labels = {location:'Localização GPS',network:'Rede do laboratório',battery:'Bateria',rotation:'Orientação e rotação',sensor:'Sensores virtuais',system:'Sistema e navegação'};
  document.querySelector('#controlTitle').textContent = labels[panel];
  document.querySelectorAll('[data-control-section]').forEach(section => { section.hidden = section.dataset.controlSection !== panel; });
  document.querySelector('#controlStatus').textContent = runtimeDevice?.state === 'on' ? 'Escolha uma ação. O estado retornado aparecerá abaixo.' : 'Android desconectado. Inicie o laboratório para usar os controles.';
  document.querySelector('#controlReadback').hidden = true;
  controlDialog.showModal();
}));
let controlBusy = false;
async function applyDeviceControl(payload) {
  if(window.huntmobTools?.extra()){
    try{const data=await window.huntmobTools.control(payload);document.querySelector('#controlStatus').textContent=data.message||data.reason||'Controle enviado.';notify(data.message||data.reason||'Controle enviado.');}catch(error){notify(error.message);}return;
  }
  if (devicePlatform === 'ios') {
    document.querySelector('#controlStatus').textContent='Aplicando no iOS…';
    try {const data=await authorizedPost('/api/ios/action',{...payload,action:'device-control',control:payload.action});document.querySelector('#controlStatus').textContent=data.reason || 'Controle aplicado no iOS.';}
    catch(error){notify(error.message);}return;
  }
  if (controlBusy) return;
  controlBusy = true;
  const controls = document.querySelectorAll('[data-control-action], [data-device-key]'); controls.forEach(button => { button.disabled = true; });
  document.querySelector('#controlStatus').textContent = 'Aplicando no Android…';
  try {
    const data = await authorizedPost('/api/device/control',{...payload,expected_device_id:activeLab.id});
    document.querySelector('#controlStatus').textContent = data.message;
    const readback = data.readback; const radio = value => value === '1' ? 'Ligado' : value === '0' ? 'Desligado' : value;
    const battery = readback.battery.match(/level: (\d+)/)?.[1];
    document.querySelector('#controlReadbackText').textContent = `Wi-Fi: ${radio(readback.wifi)}\nDados móveis: ${radio(readback.mobile)}\nLocalização: ${readback.location_enabled === 'true' ? 'Ativada' : readback.location_enabled}\nBateria: ${battery ? battery + '%' : 'Indisponível'}\nRotação: ${readback.rotation}\n${readback.acceleration || ''}\n${readback.network_shape || ''}`;
    document.querySelector('#controlReadback').hidden = false; document.querySelector('#controlReadback').open = true;
    notify(data.message);
  } catch(error) { document.querySelector('#controlStatus').textContent = error.message; notify(error.message); }
  finally { controlBusy = false; controls.forEach(button => { button.disabled = false; }); }
}
document.querySelectorAll('[data-control-action]').forEach(button => button.addEventListener('click', () => {
  const action = button.dataset.controlAction;
  const payload = {action};
  if (action === 'location') { payload.latitude = Number(document.querySelector('#gpsLatitude').value); payload.longitude = Number(document.querySelector('#gpsLongitude').value); if (!document.querySelector('#gpsLatitude').value || !document.querySelector('#gpsLongitude').value) { notify('Preencha latitude e longitude.'); return; } }
  if (action === 'network' || action === 'network-shape') payload.profile = button.dataset.profile;
  if (action === 'rotation') payload.orientation = button.dataset.orientation;
  if (action === 'battery') { if (!document.querySelector('#batteryLevel').value) { notify('Informe a carga.'); return; } payload.level = Number(document.querySelector('#batteryLevel').value); }
  if (action === 'sensor') { for (const key of ['x','y','z']) { const input = document.querySelector('#sensor' + key.toUpperCase()); if (!input.value) { notify('Preencha os três eixos.'); return; } payload[key] = Number(input.value); } }
  applyDeviceControl(payload);
}));
document.querySelectorAll('[data-device-key]').forEach(button => button.addEventListener('click', () => applyDeviceControl({action:button.dataset.deviceKey})));
document.querySelectorAll('[data-tool-shortcut]').forEach(button => button.addEventListener('click', () => { if (controlDialog.open) controlDialog.close(); document.querySelector(`[data-tab="${button.dataset.toolShortcut}"]`).click(); }));
let screenshotBusy = false;
document.querySelector('#quickScreenshot').addEventListener('click', async () => {
  if (screenshotBusy) return;
  screenshotBusy = true;
  const button = document.querySelector('#quickScreenshot');
  button.disabled = true;
  try {
    const result = devicePlatform === 'ios'
      ? await authorizedPost('/api/ios/action', {action: 'capture'})
      : await authorizedPost('/api/evidence/capture', {package_id: currentSelectedPackage});
    await downloadEvidenceJpeg(result.record);
    await loadEvidence();
    notify('JPEG baixado; captura preservada nas evidências.');
  } catch (error) {
    notify(error.message);
  } finally {
    screenshotBusy = false;
    button.disabled = runtimeDevice?.state !== 'on';
  }
});
document.querySelectorAll('[data-report-section]').forEach(button => button.addEventListener('click', () => { const target = document.getElementById(button.dataset.reportSection); if (target.closest('details')) target.closest('details').open = true; target.scrollIntoView({block:'nearest',behavior:'smooth'}); }));
tabs.forEach((tab) => { tab.tabIndex = tab.classList.contains('active') ? 0 : -1; tab.addEventListener('keydown', event => { if (!['ArrowRight','ArrowLeft','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return; event.preventDefault(); const available=[...tabs].filter(item=>!item.hidden&&!item.disabled&&!item.classList.contains('off-phase'));const index=available.indexOf(tab);const next=event.key==='Home'?0:event.key==='End'?available.length-1:(index+(['ArrowRight','ArrowDown'].includes(event.key)?1:-1)+available.length)%available.length;available[next]?.click();available[next]?.focus(); }); });

document.querySelector('#selectObservers').addEventListener('click', () => { scriptOptions.forEach(option => { option.checked = !option.disabled; }); refreshFridaSelection(); });
document.querySelector('#clearObservers').addEventListener('click', () => { scriptOptions.forEach(option => { option.checked = false; }); refreshFridaSelection(); });

document.querySelector('#openAndroidCamera').addEventListener('click', async () => { dialog.close(); await applyDeviceControl({action:'camera'}); });

try { const savedPhase = localStorage.getItem('huntmob.activePhase') || phaseForTab(localStorage.getItem('huntmob.activeTool')); const open = !analysisPanel.hidden; activatePhase(savedPhase); setAnalysisOpen(open); } catch {}
syncEngagementStepper();
