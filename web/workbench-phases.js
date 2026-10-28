// Modelo de fases do workbench. Uma taxonomia única: as 4 fases do pentest são
// a navegação, e cada fase contém o conjunto de abas (#tab-<id>) que lhe
// pertence. Substitui a navegação paralela por grupos (Laboratório/
// Investigação/Resultados). Puro — o modelo não toca o DOM; revealPhase recebe
// o document para ser testável isolado.
const PHASE_TABS = {
  engagement: ['device-tools', 'files'],
  estatico: ['reverse'],
  dinamico: ['dast', 'frida', 'proxy'],
  evidencias: ['evidence'],
};

function tabsForPhase(phase) {
  return PHASE_TABS[phase] || [];
}

// Fase dona de uma aba; cai em 'engagement' quando a aba é desconhecida
// (ex.: preferência persistida inválida em localStorage).
function phaseForTab(tabId) {
  for (const phase of Object.keys(PHASE_TABS)) {
    if (PHASE_TABS[phase].includes(tabId)) return phase;
  }
  return 'engagement';
}

// Revela no DOM o conjunto de abas (#tab-<id>) da fase: marca a fase ativa na
// espinha, mostra os painéis das abas disponíveis (ignora as com nav
// hidden/disabled, ex.: iOS) e esconde os demais. Devolve os ids revelados —
// vazio quando nenhuma aba da fase está disponível (o caller mostra o aviso).
// doc é injetado para testar isolado.
function revealPhase(phase, doc) {
  doc.querySelectorAll('.phase-spine .phase').forEach((b) => {
    const on = b.dataset.phase === phase;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  doc.querySelectorAll('.tab-content').forEach((sec) => sec.classList.remove('active'));
  const revealed = [];
  for (const id of tabsForPhase(phase)) {
    const nav = doc.querySelector(`[data-tab="${id}"]`);
    if (nav && (nav.hidden || nav.disabled)) continue;
    const sec = doc.querySelector(`#tab-${id}`);
    if (sec) { sec.classList.add('active'); revealed.push(id); }
  }
  // Aviso quando a fase não tem nenhuma aba disponível neste perfil (ex.: iOS).
  const empty = doc.querySelector('#phaseEmpty');
  if (empty) empty.hidden = revealed.length > 0;
  return revealed;
}

// Reflete no chip do header o estado real do aparelho (rótulo, online/offline,
// perfil). doc injetável. Evita o sinal fixo e enganoso do placeholder.
function updateWorkbenchChip(state, doc) {
  const dot = doc.querySelector('#workbenchDeviceDot');
  const label = doc.querySelector('#workbenchDeviceChip');
  const badge = doc.querySelector('#workbenchDeviceBadge');
  if (label) label.textContent = state.label || 'Aparelho';
  if (dot) { dot.classList.toggle('on', !!state.online); dot.classList.toggle('off', !state.online); }
  if (badge) {
    if (state.profile) { badge.textContent = state.profile; badge.hidden = false; }
    else badge.hidden = true;
  }
}

// Dual CJS/browser: no navegador este bloco é ignorado (module é undefined) e
// os nomes acima ficam visíveis a app.js pelo escopo léxico de script clássico;
// sob Node, os testes fazem require deste arquivo.
if (typeof module !== 'undefined') module.exports = { PHASE_TABS, tabsForPhase, phaseForTab, revealPhase, updateWorkbenchChip };
