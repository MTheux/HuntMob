// Modelo de fases do workbench. Uma taxonomia única: as 4 fases do pentest são
// a navegação, e cada fase contém o conjunto de abas (#tab-<id>) que lhe
// pertence. Substitui a navegação paralela por grupos (Laboratório/
// Investigação/Resultados). Puro — o modelo não toca o DOM; revealPhase recebe
// o document para ser testável isolado.
const PHASE_TABS = {
  engagement: ['device-tools', 'files', 'lab'],
  estatico: ['reverse'],
  dinamico: ['dast', 'frida', 'proxy'],
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

// Revela no DOM a fase: marca a fase ativa na espinha, apura as abas da fase
// disponíveis neste perfil (ignora as com nav hidden/disabled, ex.: iOS) e
// mostra UMA sub-aba por vez — a pedida (activeTab) quando disponível, senão a
// primeira. A sub-nav (.tool-router) vira a barra secundária da fase: as abas
// de fora recebem .off-phase, só a ativa recebe .active, e a barra some quando
// a fase tem menos de duas abas. Devolve {available, active} — available vazio
// e active undefined quando nenhuma aba está disponível (o caller mostra o
// aviso). doc é injetado para testar isolado.
function revealPhase(phase, doc, activeTab) {
  doc.querySelectorAll('.phase-spine .phase').forEach((b) => {
    const on = b.dataset.phase === phase;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  const available = [];
  for (const id of tabsForPhase(phase)) {
    const nav = doc.querySelector(`[data-tab="${id}"]`);
    if (nav && (nav.hidden || nav.disabled)) continue;
    available.push(id);
  }
  const active = available.includes(activeTab) ? activeTab : available[0];
  // Sub-nav: só as abas da fase ficam visíveis; só a ativa fica marcada.
  doc.querySelectorAll('.tool-router [data-tab]').forEach((btn) => {
    const inPhase = available.includes(btn.dataset.tab);
    btn.classList.toggle('off-phase', !inPhase);
    const on = inPhase && btn.dataset.tab === active;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', String(on));
  });
  const router = doc.querySelector('.tool-router');
  if (router) router.hidden = available.length < 2;
  // Painéis: só o da aba ativa fica visível.
  doc.querySelectorAll('.tab-content').forEach((sec) => sec.classList.remove('active'));
  if (active) {
    const sec = doc.querySelector(`#tab-${active}`);
    if (sec) sec.classList.add('active');
  }
  // Aviso quando a fase não tem nenhuma aba disponível neste perfil (ex.: iOS).
  const empty = doc.querySelector('#phaseEmpty');
  if (empty) empty.hidden = available.length > 0;
  return { available, active };
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
