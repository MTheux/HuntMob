const tabs = document.querySelectorAll('.analysis-tabs button');
const panels = document.querySelectorAll('.tab-content');
const toast = document.querySelector('.toast');
const dialog = document.querySelector('#fixtureDialog');
const preview = document.querySelector('#cameraPreview');
let stream;

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
    notify('Webcam ativa somente nesta sessão');
  } catch (_error) {
    notify('Acesso à webcam não autorizado');
  }
});

dialog.addEventListener('close', () => {
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = undefined;
  preview.srcObject = null;
  preview.classList.remove('active');
  if (dialog.returnValue && dialog.returnValue !== 'cancel') {
    notify(`Fixture registrada: ${dialog.returnValue}`);
  }
});

document.querySelectorAll('.script-row').forEach((button) => button.addEventListener('click', () => {
  notify('Template preparado; aprovação humana exigida antes da execução');
}));
document.querySelector('#openGhidra').addEventListener('click', () => notify('Abertura no Ghidra aguardando worker REA'));
document.querySelector('#newLab').addEventListener('click', () => notify('Wizard de criação será conectado ao Worker API'));
