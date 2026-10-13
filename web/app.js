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

async function deviceAction(action) {
  if (!csrfToken) {
    const session = await fetch('/api/session', { cache: 'no-store' }).then((response) => response.json());
    csrfToken = session.csrf_token;
  }
  const response = await fetch('/api/device/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-HuntMob-CSRF': csrfToken },
    body: JSON.stringify({ action, authorized: true, approved: true }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.reason || `ação recusada (${response.status})`);
  return payload;
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
  try {
    const response = await fetch('/api/runtime', { cache: 'no-store' });
    if (!response.ok) throw new Error(`runtime API ${response.status}`);
    const payload = await response.json();
    runtimeDevice = payload.devices?.[0];
    document.querySelector('#runtimeCount').textContent = String(payload.devices?.length || 0);
    if (!runtimeDevice) {
      document.querySelector('#runtimeName').textContent = 'Runtime próprio em construção';
      document.querySelector('#runtimeMeta').textContent = payload.limitations?.join(' · ') || 'Imagem AOSP HuntMob necessária';
      document.querySelector('#stageDeviceName').textContent = 'HuntMob Runtime';
      document.querySelector('#stageSerial').textContent = 'QEMU/AOSP ainda não provisionado';
      document.querySelector('#runtimeState').textContent = 'BUILD REQUIRED';
      document.querySelector('#deviceViewport').classList.add('runtime-unavailable');
      document.querySelector('#runtimePlaceholder').hidden = false;
      document.querySelectorAll('.toolbar-actions button').forEach((button) => { button.disabled = true; });
      document.querySelector('#eventKind').textContent = 'STATE';
      document.querySelector('#eventMessage').textContent = 'Nenhuma VM HuntMob em execução';
      document.querySelector('#eventReceipt').textContent = 'sem receipt';
      const status = document.querySelector('#biometricStatus');
      status.textContent = 'Aguardando o HAL biométrico da imagem AOSP HuntMob';
      status.className = 'face-status error';
      document.querySelectorAll('[data-biometric]').forEach((button) => { button.disabled = true; });
      document.querySelector('#automaticBiometric').disabled = true;
      return;
    }
    const online = runtimeDevice.state === 'on';
    document.querySelector('#deviceViewport').classList.remove('runtime-unavailable');
    document.querySelector('#runtimePlaceholder').hidden = true;
    if (online) startDeviceScreen();
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
document.querySelector('#detectApps').addEventListener('click', () => {
  notify('1 app autorizado detectado no device atual');
  packageId.value = 'br.com.huntmob.demo';
  refreshFridaSelection();
});
runFrida.addEventListener('click', () => {
  const selected = scriptOptions.filter((item) => item.checked).map((item) => item.value);
  const containsActive = selected.some((id) => id.includes('override') || id.includes('fixture'));
  fridaConsole.innerHTML = `<div>$ huntmob frida run --package ${packageId.value.trim()}</div><span>${selected.join(' + ')}</span><span>${containsActive ? ' · aprovação humana necessária' : ' · plano pronto para o worker'}</span>`;
  notify(containsActive ? 'Plano criado; confirme a ação ativa no worker' : 'Plano Frida criado com receipt obrigatório');
});
document.querySelector('#openGhidra').addEventListener('click', () => notify('Abertura no Ghidra aguardando worker REA'));
document.querySelector('#newLab').addEventListener('click', () => newLabDialog.showModal());
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
  const errorBox = document.querySelector('#labError');
  errorBox.hidden = true;
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
    errorBox.textContent = 'Iniciando Android headless…';
    errorBox.hidden = false;
    await deviceAction('start');
    newLabDialog.close();
    await loadRuntime();
    notify('Laboratório Android pronto');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
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
