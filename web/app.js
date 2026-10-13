const tabs = document.querySelectorAll('.analysis-tabs button');
const panels = document.querySelectorAll('.tab-content');
const toast = document.querySelector('.toast');
const dialog = document.querySelector('#fixtureDialog');
const preview = document.querySelector('#cameraPreview');
const overlay = document.querySelector('#faceOverlay');
const faceStatus = document.querySelector('#faceStatus');
const enrollFace = document.querySelector('#enrollFace');
const verifyFace = document.querySelector('#verifyFace');
let stream;
let human;
let enrolledEmbedding;

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
  document.querySelector('#fixtureTitle').textContent = button.dataset.panel === 'camera' ? 'Câmera' : 'Biometria facial';
  dialog.showModal();
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

document.querySelectorAll('.script-row').forEach((button) => button.addEventListener('click', () => {
  notify('Template preparado; aprovação humana exigida antes da execução');
}));
document.querySelector('#openGhidra').addEventListener('click', () => notify('Abertura no Ghidra aguardando worker REA'));
document.querySelector('#newLab').addEventListener('click', () => notify('Wizard de criação será conectado ao Worker API'));
