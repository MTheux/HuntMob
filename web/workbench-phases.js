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

// Dual CJS/browser: no navegador este bloco é ignorado (module é undefined) e
// os nomes acima ficam visíveis a app.js pelo escopo léxico de script clássico;
// sob Node, os testes fazem require deste arquivo.
if (typeof module !== 'undefined') module.exports = { PHASE_TABS, tabsForPhase, phaseForTab };
