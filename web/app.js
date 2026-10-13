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

async function authorizedPost(route, body) {
  if (!csrfToken) {
    const session = await fetch('/api/session', { cache: 'no-store' }).then((response) => response.json());
    csrfToken = session.csrf_token;
  }
  const response = await fetch(route, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-HuntMob-CSRF': csrfToken },
    body: JSON.stringify({ ...body, authorized: true, approved: true }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.reason || `ação recusada (${response.status})`);
  return payload;
}

async function deviceAction(action) {
  return authorizedPost('/api/device/action', { action });
}

function startDeviceScreen() {
  const screen = document.querySelector('#deviceScreen');
  const refresh = () => {
    screen.src = `/api/device/screenshot?t=${Date.now()}`;
  };
  screen.onload = () => {
    screen.hidden = false;
    document.querySelector('.phone-screen').hidden = true;
  };
  screen.onerror = () => { screen.hidden = true; };
  refresh();
  window.clearInterval(screenTimer);
  screenTimer = window.setInterval(refresh, 1200);
}

async function loadRuntime() {
  if (runtimeLoading) return;
  runtimeLoading = true;
  try {
    const response = await fetch('/api/runtime', { cache: 'no-store' });
    if (!response.ok) throw new Error(`runtime API ${response.status}`);
    const payload = await response.json();
    runtimeDevice = payload.devices?.[0];
    document.querySelector('#runtimeCount').textContent = String(payload.devices?.length || 0);
    if (!runtimeDevice) {
      const workerReady = payload.ready === true;
      window.clearInterval(screenTimer);
      runtimeWasOnline = false;
      document.querySelector('#runtimeDevice').hidden = true;
      document.querySelector('#runtimeEmpty').hidden = false;
      document.querySelector('#deviceScreen').hidden = true;
      document.querySelector('.phone-screen').hidden = false;
      document.querySelector('#runtimeName').textContent = workerReady ? 'Worker pronto · device desligado' : 'Runtime próprio em construção';
      document.querySelector('#runtimeMeta').textContent = workerReady ? 'Android Emulator e imagem AOSP instalados' : (payload.limitations?.join(' · ') || 'Imagem AOSP HuntMob necessária');
      document.querySelector('#stageDeviceName').textContent = 'HuntMob Runtime';
      document.querySelector('#stageSerial').textContent = workerReady ? 'nenhum device em execução' : 'QEMU/AOSP ainda não provisionado';
      document.querySelector('#runtimeState').textContent = workerReady ? 'STOPPED' : 'BUILD REQUIRED';
      document.querySelector('#deviceViewport').classList.add('runtime-unavailable');
      document.querySelector('#runtimePlaceholder').hidden = false;
      document.querySelector('#runtimePlaceholder strong').textContent = workerReady ? 'Device desligado' : 'Runtime ainda não provisionado';
      document.querySelector('#runtimePlaceholder span').textContent = workerReady ? 'Worker e imagem prontos · crie ou inicie um laboratório' : 'Prévia de interface · nenhum Android ou aplicativo está executando aqui';
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
    document.querySelector('#runtimeDevice').hidden = false;
    document.querySelector('#runtimeEmpty').hidden = true;
    document.querySelectorAll('.toolbar-actions button').forEach((button) => { button.disabled = !online; });
    document.querySelector('#deviceViewport').classList.remove('runtime-unavailable');
    document.querySelector('#runtimePlaceholder').hidden = true;
    if (online) startDeviceScreen();
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
    const bio = runtimeDevice.biometrics;
    const status = document.querySelector('#biometricStatus');
    status.textContent = bio.supported ? 'Fingerprint disponível · HuntMob virtual biometric HAL' : `Indisponível · ${bio.reason}`;
    status.className = `face-status ${bio.supported ? 'ready' : 'error'}`;
    document.querySelectorAll('[data-biometric]').forEach((button) => { button.disabled = !bio.supported; });
    document.querySelector('#automaticBiometric').disabled = !bio.supported;
  } catch (error) {
    document.querySelector('#runtimeName').textContent = 'Runtime indisponível';
    document.querySelector('#runtimeMeta').textContent = error.message;
    document.querySelector('#runtimeState').textContent = 'OFFLINE';
  } finally {
    runtimeLoading = false;
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

tabs.forEach((tab) => tab.addEventListener('click', () => {
  tabs.forEach((item) => item.classList.remove('active'));
  panels.forEach((panel) => panel.classList.remove('active'));
  tab.classList.add('active');
  document.querySelector(`#tab-${tab.dataset.tab}`).classList.add('active');
}));

document.querySelectorAll('.file').forEach((file) => file.addEventListener('click', () => {
  document.querySelectorAll('.file').forEach((item) => item.classList.remove('selected'));
  file.classList.add('selected');
  document.querySelector('#fileName').textContent = file.dataset.file || file.textContent;
  notify(`Arquivo selecionado: ${file.textContent.trim()}`);
}));

document.querySelectorAll('[data-panel]').forEach((button) => button.addEventListener('click', () => {
  const camera = button.dataset.panel === 'camera';
  document.querySelector('#fixtureTitle').textContent = camera ? 'Reconhecimento facial' : 'Biometria do device';
  document.querySelector('#deviceBiometric').hidden = camera;
  document.querySelector('#faceRecognition').hidden = !camera;
  dialog.showModal();
}));

document.querySelectorAll('[data-biometric]').forEach((button) => button.addEventListener('click', () => {
  if (!runtimeDevice?.biometrics?.supported) {
    notify('Imagem atual não suporta fingerprint; use Android 13+');
    return;
  }
    notify(`Evento “${button.textContent.trim()}” preparado para o HAL biométrico HuntMob`);
}));

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

function renderFileList(target, entries, emptyMessage) {
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
    row.textContent = typeof entry === 'string' ? entry : `${entry.path}  ·  ${entry.size} B`;
    target.append(row);
  });
}

async function loadAppFiles() {
  const selectedPackage = packageId.value.trim();
  if (!validPackage(selectedPackage)) {
    notify('Informe um package ID válido');
    return;
  }
  document.querySelector('#filesPackage').textContent = selectedPackage;
  document.querySelector('#sandboxRoot').textContent = `/data/user/0/${selectedPackage} · alias /data/data/${selectedPackage}`;
  try {
    const response = await fetch(`/api/device/files?package=${encodeURIComponent(selectedPackage)}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.reason || `files API ${response.status}`);
    renderFileList(document.querySelector('#apkFiles'), payload.apk.entries, 'APK sem entradas legíveis.');
    renderFileList(document.querySelector('#sandboxFiles'), payload.sandbox.entries, payload.sandbox.reason || 'Sandbox vazio.');
    notify(`${payload.apk.entries.length} entradas do APK · ${payload.sandbox.entries.length} caminhos no sandbox`);
  } catch (error) {
    renderFileList(document.querySelector('#apkFiles'), [], error.message);
    renderFileList(document.querySelector('#sandboxFiles'), [], error.message);
    notify(error.message);
  }
}

document.querySelector('#refreshFiles').addEventListener('click', loadAppFiles);

function selectApp(packageName) {
  packageId.value = packageName;
  document.querySelector('#reversePackage').textContent = packageName;
  document.querySelector('#prepareReverse').disabled = false;
  document.querySelector('#reverseHash').textContent = 'SHA256 pendente';
  refreshFridaSelection();
}

async function loadInstalledApps() {
  const target = document.querySelector('#installedApps');
  target.innerHTML = '<p>Consultando device…</p>';
  try {
    const response = await fetch('/api/device/apps', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.reason || `apps API ${response.status}`);
    target.replaceChildren();
    if (!payload.apps.length) {
      target.innerHTML = '<p>Nenhum app de terceiro instalado.</p>';
      notify('Nenhum app de terceiro instalado no device');
      return [];
    }
    payload.apps.forEach((app) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.textContent = app.package_id;
      row.addEventListener('click', () => selectApp(app.package_id));
      target.append(row);
    });
    notify(`${payload.apps.length} app(s) instalado(s) detectado(s)`);
    return payload.apps;
  } catch (error) {
    target.innerHTML = `<p>${error.message}</p>`;
    notify(error.message);
    return [];
  }
}

document.querySelector('#refreshApps').addEventListener('click', loadInstalledApps);
document.querySelector('#prepareReverse').addEventListener('click', async () => {
  const selectedPackage = packageId.value.trim();
  if (!validPackage(selectedPackage)) return notify('Selecione um package válido');
  const output = document.querySelector('#reverseOutput');
  output.innerHTML = '<strong>Extraindo APK e executando JADX…</strong><p>Isso pode levar alguns minutos.</p>';
  try {
    const payload = await authorizedPost('/api/reverse', { package_id: selectedPackage });
    document.querySelector('#reverseHash').textContent = `SHA256 · ${payload.sha256.slice(0, 8)}…${payload.sha256.slice(-4)}`;
    document.querySelector('#fileName').textContent = `${payload.files.length} arquivos decompilados`;
    output.replaceChildren();
    const list = document.createElement('div');
    list.className = 'runtime-file-tree';
    renderFileList(list, payload.files, 'JADX não produziu arquivos legíveis.');
    output.append(list);
    notify(`Workspace REA criado para ${selectedPackage}`);
  } catch (error) {
    output.innerHTML = `<strong>Análise não concluída</strong><p>${error.message}</p>`;
    notify(error.message);
  }
});

function refreshFridaSelection() {
  const selected = scriptOptions.filter((item) => item.checked);
  selectedCount.textContent = `${selected.length} selecionado${selected.length === 1 ? '' : 's'}`;
  runFrida.disabled = selected.length === 0 || !validPackage(packageId.value);
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
runFrida.addEventListener('click', () => {
  const selected = scriptOptions.filter((item) => item.checked).map((item) => item.value);
  const containsActive = selected.some((id) => id.includes('override') || id.includes('fixture'));
  fridaConsole.innerHTML = `<div>$ huntmob frida run --package ${packageId.value.trim()}</div><span>${selected.join(' + ')}</span><span>${containsActive ? ' · aprovação humana necessária' : ' · plano pronto para o worker'}</span>`;
  notify(containsActive ? 'Plano criado; confirme a ação ativa no worker' : 'Plano Frida criado com receipt obrigatório');
});
document.querySelector('#openGhidra').addEventListener('click', () => notify('Selecione uma biblioteca nativa .so antes de abrir no Ghidra'));

async function refreshProxyStatus() {
  const port = Number(document.querySelector('#proxyPort').value);
  try {
    const payload = await fetch(`/api/proxy?port=${port}`, { cache: 'no-store' }).then((response) => response.json());
    const active = payload.configured && payload.listener;
    document.querySelector('#proxyStatus').textContent = payload.listener ? `Listener ativo · device ${payload.device_proxy || 'sem rota'}` : `Nenhum listener em 127.0.0.1:${port}`;
    document.querySelector('#proxyBadge').textContent = active ? 'Capturando' : 'Desconectado';
    document.querySelector('#captureTitle').textContent = active ? 'Captura ativa' : 'Captura inativa';
    document.querySelector('#startCapture').hidden = active;
    document.querySelector('#stopCapture').hidden = !active;
  } catch (error) { document.querySelector('#proxyStatus').textContent = error.message; }
}

async function proxyAction(action) {
  const port = Number(document.querySelector('#proxyPort').value);
  const payload = await authorizedPost('/api/proxy', { action, port });
  const active = action !== 'clear';
  document.querySelector('#captureTitle').textContent = active ? 'Captura ativa' : 'Captura inativa';
  document.querySelector('#startCapture').hidden = active;
  document.querySelector('#stopCapture').hidden = !active;
  if (payload.web_url) {
    const link = document.querySelector('#openProxyWeb');
    link.href = payload.web_url;
    link.hidden = false;
    document.querySelector('#captureHelp').textContent = 'Tráfego roteado ao proxy gerenciado. Para HTTPS, instale conscientemente a CA do laboratório no device.';
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
  try { await proxyAction('clear'); document.querySelector('#openProxyWeb').hidden = true; notify('Rota de proxy removida do device'); } catch (error) { notify(error.message); }
});
document.querySelector('#proxyPort').addEventListener('change', refreshProxyStatus);
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
    labError.textContent = 'Android ativo: selecione APK local para instalar e abrir neste device.';
    labError.hidden = false;
    createLabButton.disabled = false;
  }
  newLabDialog.showModal();
});
document.querySelector('#closeNewLab').addEventListener('click', () => newLabDialog.close('cancel'));
newLabDialog.addEventListener('close', resetNewLabProgress);
document.querySelector('#labSource').addEventListener('change', (event) => {
  const source = event.target.value;
  const labels = {
    empty: 'Cria um Android vazio em modo headless. Você poderá instalar o app depois.',
    upload: 'Selecione um APK/AAB local; o worker calculará SHA-256 antes da instalação.',
    firebase: 'O worker usará uma referência Firebase e credenciais guardadas no servidor.',
    'signed-url': 'A URL assinada será resolvida apenas no worker e nunca ficará no navegador.',
    'play-manual': 'A instalação pela loja requer login e autorização manual dentro do device.',
  };
  document.querySelector('#artifactField').hidden = source !== 'upload';
  document.querySelector('#labPlan').textContent = labels[source];
});
document.querySelector('#newLabForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const packageValue = document.querySelector('#labPackage').value.trim();
  const source = document.querySelector('#labSource').value;
  const errorBox = labError;
  errorBox.hidden = true;
  if (runtimeDevice?.state === 'on' && source !== 'upload') {
    errorBox.textContent = 'Já existe um laboratório Android ativo. Encerre a sessão atual antes de criar outro.';
    errorBox.hidden = false;
    return;
  }
  if (packageValue && !validPackage(packageValue)) {
    errorBox.textContent = 'Package ID inválido. Use o formato br.com.empresa.app ou deixe vazio para detecção automática.';
    errorBox.hidden = false;
    return;
  }
  if (!document.querySelector('#labApproval').checked) {
    errorBox.textContent = 'Confirme a autorização do engagement antes de iniciar.';
    errorBox.hidden = false;
    return;
  }
  if (source === 'upload' && !document.querySelector('#labArtifact').files.length) {
    errorBox.textContent = 'Selecione um APK ou AAB, ou escolha “Device vazio”.';
    errorBox.hidden = false;
    return;
  }
  try {
    createLabButton.disabled = true;
    createLabButton.textContent = 'Iniciando…';
    errorBox.textContent = 'Iniciando Android headless…';
    errorBox.hidden = false;
    if (source === 'upload') {
      const artifact = document.querySelector('#labArtifact').files[0];
      if (!artifact.name.toLowerCase().endsWith('.apk')) throw new Error('Envie um APK instalável. AAB precisa ser convertido antes.');
      errorBox.textContent = 'Enviando APK, preparando Android e abrindo o app…';
      if (!csrfToken) csrfToken = (await fetch('/api/session').then(response => response.json())).csrf_token;
      const response = await fetch('/api/device/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/vnd.android.package-archive', 'X-HuntMob-CSRF': csrfToken, 'X-HuntMob-Approved': 'true' },
        body: artifact,
      });
      const result = await response.json();
      if (!response.ok || !result.launched) throw new Error(result.reason || 'Não foi possível abrir o APK');
      selectApp(result.package_id);
      await loadInstalledApps();
    } else if (source === 'empty') {
      await deviceAction('start');
    } else {
      throw new Error('Esta origem ainda não está integrada. Use APK local ou Device vazio.');
    }
    newLabDialog.close();
    await loadRuntime();
    notify('Laboratório Android pronto');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    createLabButton.disabled = false;
    createLabButton.textContent = 'Criar e iniciar laboratório';
  }
});
const sessionDialog = document.querySelector('#sessionDialog');
document.querySelector('#stopDevice').addEventListener('click', () => sessionDialog.showModal());
document.querySelector('#rebootDevice').addEventListener('click', async () => {
  notify('Reiniciando Android…');
  try { await deviceAction('reboot'); await loadRuntime(); notify('Android reiniciado'); } catch (error) { notify(error.message); }
});
document.querySelector('#powerOffDevice').addEventListener('click', async () => {
  try { await deviceAction('stop'); sessionDialog.close(); window.clearInterval(screenTimer); await loadRuntime(); notify('Device desligado; dados preservados'); } catch (error) { notify(error.message); }
});
document.querySelector('#destroyDevice').addEventListener('click', async () => {
  try { await deviceAction('destroy'); sessionDialog.close(); window.clearInterval(screenTimer); await loadRuntime(); notify('Sessão e dados do AVD foram descartados'); } catch (error) { notify(error.message); }
});
loadRuntime();
refreshProxyStatus();
window.setInterval(loadRuntime, 2500);

const interactiveScreen = document.querySelector('#deviceScreen');
let pointerStart;
function screenPoint(event) {
  const rect = interactiveScreen.getBoundingClientRect();
  const scale = Math.min(rect.width / interactiveScreen.naturalWidth, rect.height / interactiveScreen.naturalHeight);
  const width = interactiveScreen.naturalWidth * scale;
  const height = interactiveScreen.naturalHeight * scale;
  return { x: (event.clientX - rect.left - (rect.width - width) / 2) / width, y: (event.clientY - rect.top - (rect.height - height) / 2) / height };
}
interactiveScreen.style.touchAction = 'none';
interactiveScreen.tabIndex = 0;
interactiveScreen.addEventListener('pointerdown', event => {
  pointerStart = screenPoint(event);
  interactiveScreen.setPointerCapture(event.pointerId);
});
interactiveScreen.addEventListener('pointerup', async event => {
  if (!pointerStart) return;
  const end = screenPoint(event);
  const start = pointerStart;
  pointerStart = undefined;
  if (![start.x, start.y, end.x, end.y].every(value => value >= 0 && value <= 1)) return;
  const swipe = Math.hypot(end.x - start.x, end.y - start.y) > 0.025;
  try {
    await authorizedPost('/api/device/input', {action: swipe ? 'swipe' : 'tap', ...start, end_x: end.x, end_y: end.y});
  } catch (error) { notify(error.message); }
});
interactiveScreen.addEventListener('keydown', async event => {
  const action = event.key === 'Escape' ? 'back' : (event.key.length === 1 && /^[A-Za-z0-9 @._+:/-]$/.test(event.key) ? 'text' : null);
  if (!action) return;
  event.preventDefault();
  try { await authorizedPost('/api/device/input', {action, text: event.key}); } catch (error) { notify(error.message); }
});
document.querySelector('#deviceBack').addEventListener('click', async () => {
  try { await authorizedPost('/api/device/input', {action: 'back'}); } catch (error) { notify(error.message); }
});
